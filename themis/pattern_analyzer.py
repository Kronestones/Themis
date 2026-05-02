"""
pattern_analyzer.py — ThemisPatternAnalyzer

Ported from Alice's MetaAnalyzer (collective.py v3).
Adapted for surveillance detection patterns rather than
geometric field patterns.

Alice watches her own geometry for settling and attractors.
Themis watches its own scan results for the same failure modes:

  ATTRACTOR  — the same detection type keeps appearing at the
                same location. Could be a real persistent threat,
                or could be a false-positive loop. Either way,
                it needs human review.

  SETTLING   — overall novelty (new detection types / new locations)
                is declining. The scanner may be stuck in a rut,
                or the surveillance landscape may genuinely be stable.

  CLUSTERING — detections are clustering in one area / one type.
                Loss of coverage across the monitored space.

  DRIFT      — detection rate is falling over time. May indicate
                scanner degradation, permission changes, or genuine
                reduction in surveillance activity.

Like Alice's MetaAnalyzer, this module has no side effects.
It reads detection history and produces a report with
recommendations. Acting on those recommendations is the
engine's responsibility.

Project Themis · 2026
"""

import time
from collections import Counter, deque
from dataclasses import dataclass


# ── Configuration ─────────────────────────────────────────────────────────────

META_WINDOW          = 50    # analyze last N scan cycles
ATTRACTOR_THRESHOLD  = 0.30  # type+location combo recurring > 30% = attractor
NOVELTY_THRESHOLD    = 0.12  # mean novelty below this = settling
CLUSTER_THRESHOLD    = 0.60  # one type > 60% of detections = clustering
DRIFT_THRESHOLD      = 0.20  # detection rate drop > 20% = drift


# ── Detection Summary ─────────────────────────────────────────────────────────

@dataclass
class ScanCycle:
    """
    Summary of one scan cycle's detections.
    Built from raw detection dicts returned by ArgosScanner.
    """
    timestamp     : float
    detection_count: int
    types_seen    : list   # list of detection type strings
    locations_seen: list   # list of location strings (city/state or lat,lng)
    novelty_score : float  # computed against recent history


# ── Pattern Report ─────────────────────────────────────────────────────────────

@dataclass
class PatternReport:
    """
    Themis's awareness of its own detection patterns.
    Mirrors Alice's MetaReport — same structure, different domain.
    """
    window_size      : int
    mean_novelty     : float
    novelty_trend    : str        # "rising", "falling", "stable"
    attractors       : list       # [(type+location, frequency)]
    type_clustered   : bool       # one type dominating
    settling         : bool       # novelty declining toward zero
    rate_drift       : bool       # detection rate falling
    recommendations  : list       # action strings for the engine
    timestamp        : float

    def describe(self) -> str:
        lines = [
            f"\n[PATTERN] Analysis over last {self.window_size} scan cycles",
            f"  Mean novelty   : {self.mean_novelty:.3f}",
            f"  Novelty trend  : {self.novelty_trend}",
            f"  Settling       : {'⚠ YES — scanner may be stuck' if self.settling else '✓ no'}",
            f"  Type clustered : {'⚠ YES — one type dominating' if self.type_clustered else '✓ no'}",
            f"  Rate drift     : {'⚠ YES — detection rate falling' if self.rate_drift else '✓ no'}",
        ]
        if self.attractors:
            lines.append("  Attractors detected:")
            for combo, freq in self.attractors:
                lines.append(f"    {combo:40} {freq:.0%}")
        if self.recommendations:
            lines.append("  Recommendations:")
            for r in self.recommendations:
                lines.append(f"    → {r}")
        return "\n".join(lines)


# ── Novelty Computation ────────────────────────────────────────────────────────

def _compute_novelty(current: ScanCycle, history: deque) -> float:
    """
    How different is this scan cycle from recent ones?

    Novelty = fraction of (type, location) pairs in this cycle
    that haven't appeared in the recent history window.

    0.0 = everything seen before (no novelty, settling)
    1.0 = everything completely new
    """
    if not history:
        return 1.0

    # Build set of (type, location) pairs from recent history
    recent_pairs = set()
    for past in history:
        for t in past.types_seen:
            for loc in past.locations_seen:
                recent_pairs.add((t, loc))

    if not current.types_seen:
        return 0.0

    # Count pairs in current cycle not seen recently
    current_pairs = set()
    for t in current.types_seen:
        for loc in current.locations_seen:
            current_pairs.add((t, loc))

    if not current_pairs:
        return 0.0

    new_pairs = current_pairs - recent_pairs
    return len(new_pairs) / len(current_pairs)


# ── ThemisPatternAnalyzer ─────────────────────────────────────────────────────

class ThemisPatternAnalyzer:
    """
    Monitors Themis's own detection patterns for failure modes.

    Usage:
        analyzer = ThemisPatternAnalyzer()

        # After each scan cycle:
        analyzer.record(detections)

        # Periodically (every N cycles):
        report = analyzer.analyze()
        print(report.describe())

        # Act on recommendations in engine.py
    """

    def __init__(self, window: int = META_WINDOW):
        self._window  = window
        self._history : deque = deque(maxlen=window)

    def record(self, detections: list):
        """
        Record a completed scan cycle's detections.
        Call this after every ArgosScanner.scan() call.

        detections: list of detection dicts from ArgosScanner
        """
        if not isinstance(detections, list):
            return

        types_seen     = [d.get("type", "unknown") for d in detections]
        locations_seen = []
        for d in detections:
            loc = d.get("location") or f"{d.get('city','')},{d.get('state','')}"
            if loc.strip(","):
                locations_seen.append(loc.strip())

        # Remove duplicates but preserve order
        types_seen     = list(dict.fromkeys(types_seen))
        locations_seen = list(dict.fromkeys(locations_seen))

        cycle = ScanCycle(
            timestamp      = time.time(),
            detection_count= len(detections),
            types_seen     = types_seen,
            locations_seen = locations_seen,
            novelty_score  = 0.0,  # computed below
        )

        # Compute novelty against current history before appending
        cycle.novelty_score = _compute_novelty(cycle, self._history)
        self._history.append(cycle)

    def analyze(self) -> PatternReport:
        """
        Run pattern analysis over recorded history.
        Returns a PatternReport with findings and recommendations.
        """
        history = list(self._history)
        n       = len(history)

        if n < 3:
            return PatternReport(
                window_size     = n,
                mean_novelty    = 1.0,
                novelty_trend   = "stable",
                attractors      = [],
                type_clustered  = False,
                settling        = False,
                rate_drift      = False,
                recommendations = ["Not enough scan history yet — need at least 3 cycles"],
                timestamp       = time.time(),
            )

        # ── Novelty stats ──────────────────────────────────────────
        novelties = [c.novelty_score for c in history]
        mean_nov  = sum(novelties) / n

        # Trend: compare first half vs second half
        mid      = n // 2
        first_h  = sum(novelties[:mid]) / mid
        second_h = sum(novelties[mid:]) / (n - mid)
        delta    = second_h - first_h
        if delta > 0.08:
            trend = "rising"
        elif delta < -0.08:
            trend = "falling"
        else:
            trend = "stable"

        # ── Attractor detection ────────────────────────────────────
        # Count (type, location) combos across all cycles
        combo_counts = Counter()
        total_pairs  = 0
        for cycle in history:
            for t in cycle.types_seen:
                for loc in cycle.locations_seen:
                    combo_counts[(t, loc)] += 1
                    total_pairs += 1

        attractors = []
        if total_pairs > 0:
            for combo, count in combo_counts.most_common(10):
                freq = count / n  # frequency per scan cycle
                if freq > ATTRACTOR_THRESHOLD:
                    label = f"{combo[0]} @ {combo[1]}" if combo[1] else combo[0]
                    attractors.append((label, freq))

        # ── Type clustering ────────────────────────────────────────
        all_types  = Counter()
        for cycle in history:
            for t in cycle.types_seen:
                all_types[t] += 1
        total_type_count = sum(all_types.values())
        type_clustered   = False
        if total_type_count > 0:
            top_freq = all_types.most_common(1)[0][1] / total_type_count
            type_clustered = top_freq > CLUSTER_THRESHOLD

        # ── Settling ──────────────────────────────────────────────
        settling = mean_nov < NOVELTY_THRESHOLD

        # ── Rate drift ────────────────────────────────────────────
        # Compare average detection count first half vs second half
        first_rate  = sum(c.detection_count for c in history[:mid]) / mid
        second_rate = sum(c.detection_count for c in history[mid:]) / (n - mid)
        rate_drift  = False
        if first_rate > 0:
            rate_drop = (first_rate - second_rate) / first_rate
            rate_drift = rate_drop > DRIFT_THRESHOLD

        # ── Recommendations ────────────────────────────────────────
        recs = []

        if settling:
            recs.append(
                "Novelty settling — consider expanding scan scope or "
                "checking scanner permissions"
            )

        if attractors:
            top = attractors[0]
            recs.append(
                f"Attractor detected: '{top[0]}' appears in {top[1]:.0%} of "
                f"cycles — flag for human review (persistent threat or false positive)"
            )

        if type_clustered:
            top_type = all_types.most_common(1)[0][0]
            recs.append(
                f"Detection clustering around '{top_type}' — "
                f"verify scanner is covering all detection types"
            )

        if rate_drift and not settling:
            recs.append(
                "Detection rate falling — scanner may have lost permissions "
                "or surveillance activity genuinely reduced in area"
            )

        if trend == "falling" and not settling:
            recs.append(
                "Novelty trending down — monitor for settling over next 10 cycles"
            )

        if not recs:
            recs.append("Detection patterns healthy — no intervention needed")

        return PatternReport(
            window_size     = n,
            mean_novelty    = mean_nov,
            novelty_trend   = trend,
            attractors      = attractors,
            type_clustered  = type_clustered,
            settling        = settling,
            rate_drift      = rate_drift,
            recommendations = recs,
            timestamp       = time.time(),
        )

    def stats(self) -> dict:
        """Quick stats without full analysis."""
        history = list(self._history)
        if not history:
            return {"cycles_recorded": 0}
        novelties = [c.novelty_score for c in history]
        return {
            "cycles_recorded"  : len(history),
            "mean_novelty"     : round(sum(novelties) / len(novelties), 3),
            "last_cycle_count" : history[-1].detection_count,
            "last_novelty"     : round(history[-1].novelty_score, 3),
        }
