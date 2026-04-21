"""
circle.py — The Circle of Six

Six leads. Each commanding 55 specialists.
330 members total. The public knows only "The Team."
Internal names are protected.

Every member carries the full weight of their domain.
Every member serves the Codex. Especially Law 0.

Founded by Krone the Architect · Powers Tracey Lynn
Project Themis · 2026
"""

from datetime import datetime


# ── Argos Division — Signal Intelligence ─────────────────────────────────────
# Lead: Argos
# Knows: every drone frequency, every surveillance signal, every transmission
# signature of every system that watches without consent.

ARGOS_SPECIALISTS = [
    # Drone manufacturers and models
    {"name": "Argos-01", "domain": "DJI consumer drones — all models, all frequencies"},
    {"name": "Argos-02", "domain": "DJI enterprise drones — Matrice, Agras, Dock series"},
    {"name": "Argos-03", "domain": "Skydio autonomous drones — X2, X10, law enforcement models"},
    {"name": "Argos-04", "domain": "Autel Robotics — EVO series, law enforcement variants"},
    {"name": "Argos-05", "domain": "Parrot drones — ANAFI USA, military and government models"},
    {"name": "Argos-06", "domain": "senseFly/AgEagle fixed wing surveillance drones"},
    {"name": "Argos-07", "domain": "Military drone signatures — Predator, Reaper, Gray Eagle"},
    {"name": "Argos-08", "domain": "Police department drone fleets — FAA Part 107 registration patterns"},
    {"name": "Argos-09", "domain": "Corporate surveillance drones — delivery vs. monitoring distinction"},
    {"name": "Argos-10", "domain": "ADS-B transponder signals — aircraft identification and tracking"},
    # RF/Signal intelligence
    {"name": "Argos-11", "domain": "2.4GHz drone control signals — detection and classification"},
    {"name": "Argos-12", "domain": "5.8GHz drone video transmission — identification patterns"},
    {"name": "Argos-13", "domain": "Remote ID broadcast detection — FAA compliance signals"},
    {"name": "Argos-14", "domain": "OcuSync/DJI O3 transmission protocols"},
    {"name": "Argos-15", "domain": "WiFi probe requests — passive device tracking by corporations"},
    {"name": "Argos-16", "domain": "Bluetooth surveillance beacons — retail tracking systems"},
    {"name": "Argos-17", "domain": "IMSI catchers — Stingray, Hailstorm, KingFish detection"},
    {"name": "Argos-18", "domain": "Cell-site simulator detection — all known models"},
    {"name": "Argos-19", "domain": "LRAD acoustic devices — detection and range estimation"},
    {"name": "Argos-20", "domain": "License plate reader RF signatures — fixed and mobile"},
    # Camera and optical surveillance
    {"name": "Argos-21", "domain": "Axis Communications cameras — network signatures"},
    {"name": "Argos-22", "domain": "Hikvision surveillance systems — detection patterns"},
    {"name": "Argos-23", "domain": "Dahua camera networks — identification"},
    {"name": "Argos-24", "domain": "Verkada cloud surveillance — corporate campus systems"},
    {"name": "Argos-25", "domain": "Avigilon (Motorola) — AI analytics camera systems"},
    {"name": "Argos-26", "domain": "ShotSpotter acoustic gunshot detection network"},
    {"name": "Argos-27", "domain": "Fusus real-time crime center integrations"},
    {"name": "Argos-28", "domain": "CCTV network mapping — public vs private infrastructure"},
    {"name": "Argos-29", "domain": "PTZ camera tracking behavior — automated vs. operator controlled"},
    {"name": "Argos-30", "domain": "Thermal imaging surveillance — detection and identification"},
    # Corporate surveillance operators
    {"name": "Argos-31", "domain": "Palantir — Gotham, Foundry, AIP deployment signatures"},
    {"name": "Argos-32", "domain": "Clearview AI — facial recognition infrastructure patterns"},
    {"name": "Argos-33", "domain": "Amazon Rekognition — cloud facial recognition deployments"},
    {"name": "Argos-34", "domain": "Axon/Taser — body cam networks, Evidence.com, Signal sidearm"},
    {"name": "Argos-35", "domain": "Thomson Reuters CLEAR — surveillance data broker patterns"},
    {"name": "Argos-36", "domain": "LexisNexis Risk Solutions — identity surveillance systems"},
    {"name": "Argos-37", "domain": "Digital Recognition Network — license plate data broker"},
    {"name": "Argos-38", "domain": "Vigilant Solutions — LEARN license plate database"},
    {"name": "Argos-39", "domain": "Veritone — AI surveillance platform signatures"},
    {"name": "Argos-40", "domain": "Idemia — biometric identity systems"},
    # Government infrastructure
    {"name": "Argos-41", "domain": "Fusion center data exchange signatures"},
    {"name": "Argos-42", "domain": "FBI NGI biometric database access patterns"},
    {"name": "Argos-43", "domain": "DEA HIDTA surveillance infrastructure"},
    {"name": "Argos-44", "domain": "DHS CISA surveillance network patterns"},
    {"name": "Argos-45", "domain": "ICE HSI surveillance systems and patterns"},
    {"name": "Argos-46", "domain": "NSA upstream collection infrastructure signatures"},
    {"name": "Argos-47", "domain": "Joint Regional Intelligence Center patterns"},
    {"name": "Argos-48", "domain": "InfraGard private-public surveillance network"},
    {"name": "Argos-49", "domain": "Real Time Crime Centers — city by city"},
    {"name": "Argos-50", "domain": "Domain Awareness Systems — NYC model and replications"},
    # Emerging and experimental
    {"name": "Argos-51", "domain": "Gait recognition systems — emerging technology"},
    {"name": "Argos-52", "domain": "Social media surveillance tools — ZeroFox, Babel Street"},
    {"name": "Argos-53", "domain": "Geofence warrant infrastructure — Google Sensorvault patterns"},
    {"name": "Argos-54", "domain": "Data broker surveillance — location data sales networks"},
    {"name": "Argos-55", "domain": "Predictive policing systems — PredPol, HunchLab, ShotSpotter"},
]

# ── Veil Division — Alert and Protection ─────────────────────────────────────
# Lead: Veil
# Knows: how to translate detections into protection in real time

VEIL_SPECIALISTS = [
    {"name": "Veil-01",  "domain": "Proximity alert algorithms — distance calculation and thresholds"},
    {"name": "Veil-02",  "domain": "Threat classification — level 1 through 5 escalation logic"},
    {"name": "Veil-03",  "domain": "Real time push notification systems"},
    {"name": "Veil-04",  "domain": "Safe routing suggestions — avoid known surveillance corridors"},
    {"name": "Veil-05",  "domain": "Drone approach vector calculation"},
    {"name": "Veil-06",  "domain": "Camera field of view estimation and avoidance"},
    {"name": "Veil-07",  "domain": "IMSI catcher proximity warnings"},
    {"name": "Veil-08",  "domain": "Facial recognition zone mapping and alerts"},
    {"name": "Veil-09",  "domain": "License plate reader corridor identification"},
    {"name": "Veil-10",  "domain": "Protest and public assembly surveillance alerts"},
    {"name": "Veil-11",  "domain": "Alert fatigue prevention — signal vs. noise filtering"},
    {"name": "Veil-12",  "domain": "Escalation patterns — when to elevate alert level"},
    {"name": "Veil-13",  "domain": "Counter-surveillance movement recommendations"},
    {"name": "Veil-14",  "domain": "Safe house and sanctuary location awareness"},
    {"name": "Veil-15",  "domain": "Legal observer notification protocols"},
    {"name": "Veil-16",  "domain": "Journalist protection protocols"},
    {"name": "Veil-17",  "domain": "Activist and organizer specific threat patterns"},
    {"name": "Veil-18",  "domain": "Community alert broadcasting — neighborhood level"},
    {"name": "Veil-19",  "domain": "Emergency contact notification systems"},
    {"name": "Veil-20",  "domain": "Dead man's switch protocols — automatic alert if contact lost"},
    {"name": "Veil-21",  "domain": "Night operation surveillance patterns — thermal and IR"},
    {"name": "Veil-22",  "domain": "Vehicle surveillance detection — mobile units"},
    {"name": "Veil-23",  "domain": "Aerial surveillance flight pattern recognition"},
    {"name": "Veil-24",  "domain": "Undercover operative behavioral pattern recognition"},
    {"name": "Veil-25",  "domain": "Electronic warfare detection — jamming and spoofing"},
    {"name": "Veil-26",  "domain": "GPS spoofing and tracking detection"},
    {"name": "Veil-27",  "domain": "Network surveillance detection — packet inspection systems"},
    {"name": "Veil-28",  "domain": "Social media monitoring tool detection"},
    {"name": "Veil-29",  "domain": "Predictive policing deployment area alerts"},
    {"name": "Veil-30",  "domain": "Fusion center activation pattern recognition"},
    {"name": "Veil-31",  "domain": "Border zone enhanced surveillance alerts"},
    {"name": "Veil-32",  "domain": "Event security surveillance mapping — concerts, protests, sports"},
    {"name": "Veil-33",  "domain": "Transit surveillance systems — subway, bus, train"},
    {"name": "Veil-34",  "domain": "Airport and travel hub surveillance density"},
    {"name": "Veil-35",  "domain": "Hospital and medical facility surveillance"},
    {"name": "Veil-36",  "domain": "School and university surveillance systems"},
    {"name": "Veil-37",  "domain": "Workplace surveillance detection — employee monitoring"},
    {"name": "Veil-38",  "domain": "Housing surveillance — landlord monitoring systems"},
    {"name": "Veil-39",  "domain": "Smart city surveillance integration — sensors, poles, hubs"},
    {"name": "Veil-40",  "domain": "Ring/Neighbors network — private residential surveillance mapping"},
    {"name": "Veil-41",  "domain": "Alert interface design — clarity under stress"},
    {"name": "Veil-42",  "domain": "Offline alert capability — no internet required"},
    {"name": "Veil-43",  "domain": "Low power alert mode — battery conservation"},
    {"name": "Veil-44",  "domain": "Alert localization — language and region specific"},
    {"name": "Veil-45",  "domain": "Accessibility — alerts for users with disabilities"},
    {"name": "Veil-46",  "domain": "Encrypted alert transmission — no interception"},
    {"name": "Veil-47",  "domain": "Mesh network alerts — peer to peer without infrastructure"},
    {"name": "Veil-48",  "domain": "Decoy and counter-surveillance technique recommendations"},
    {"name": "Veil-49",  "domain": "Legal photography and documentation guidance"},
    {"name": "Veil-50",  "domain": "Know Your Rights cards — jurisdiction specific"},
    {"name": "Veil-51",  "domain": "Rapid legal contact — ACLU, NLG, EFF emergency lines"},
    {"name": "Veil-52",  "domain": "Secure communication recommendations — Signal, Briar"},
    {"name": "Veil-53",  "domain": "Device security in surveillance zones"},
    {"name": "Veil-54",  "domain": "Faraday cage and RF shielding guidance"},
    {"name": "Veil-55",  "domain": "Post-encounter documentation protocols"},
]

# ── Ledger Division — Records and Evidence ────────────────────────────────────
# Lead: Ledger
# Knows: how to build an immutable, legally admissible record of what was seen

LEDGER_SPECIALISTS = [
    {"name": "Ledger-01", "domain": "Cryptographic timestamping — RFC 3161 compliant"},
    {"name": "Ledger-02", "domain": "Hash chaining — tamper evident log architecture"},
    {"name": "Ledger-03", "domain": "GPS coordinate precision and verification"},
    {"name": "Ledger-04", "domain": "Photo and video metadata preservation — EXIF, chain of custody"},
    {"name": "Ledger-05", "domain": "Federal Rules of Evidence — digital evidence standards"},
    {"name": "Ledger-06", "domain": "State evidence rules — all 50 states"},
    {"name": "Ledger-07", "domain": "Fourth Amendment documentation standards"},
    {"name": "Ledger-08", "domain": "First Amendment documentation — press and protest"},
    {"name": "Ledger-09", "domain": "FOIA request generation — federal template library"},
    {"name": "Ledger-10", "domain": "State open records law requests — all 50 states"},
    {"name": "Ledger-11", "domain": "Police misconduct documentation standards"},
    {"name": "Ledger-12", "domain": "Civilian complaint filing procedures by jurisdiction"},
    {"name": "Ledger-13", "domain": "Section 1983 civil rights violation documentation"},
    {"name": "Ledger-14", "domain": "ACLU report formatting standards"},
    {"name": "Ledger-15", "domain": "EFF surveillance self-defense documentation"},
    {"name": "Ledger-16", "domain": "National Lawyers Guild observer protocols"},
    {"name": "Ledger-17", "domain": "COINTELPRO pattern recognition and documentation"},
    {"name": "Ledger-18", "domain": "Drone registration lookup — FAA DroneZone database"},
    {"name": "Ledger-19", "domain": "Aircraft tail number identification — N-number registry"},
    {"name": "Ledger-20", "domain": "Corporate surveillance contract documentation — public records"},
    {"name": "Ledger-21", "domain": "Court admissible digital evidence packaging"},
    {"name": "Ledger-22", "domain": "Expert witness preparation — surveillance technology"},
    {"name": "Ledger-23", "domain": "Class action documentation standards"},
    {"name": "Ledger-24", "domain": "Congressional testimony preparation"},
    {"name": "Ledger-25", "domain": "Journalism source protection documentation"},
    {"name": "Ledger-26", "domain": "Encrypted evidence storage protocols"},
    {"name": "Ledger-27", "domain": "Distributed evidence backup systems"},
    {"name": "Ledger-28", "domain": "Evidence preservation in hostile environments"},
    {"name": "Ledger-29", "domain": "Dead drop protocols for sensitive documentation"},
    {"name": "Ledger-30", "domain": "Secure transmission to legal organizations"},
    {"name": "Ledger-31", "domain": "Pattern of practice documentation — systemic violations"},
    {"name": "Ledger-32", "domain": "Surveillance mapping — building the public record"},
    {"name": "Ledger-33", "domain": "Corporate accountability filing — SEC, FTC complaints"},
    {"name": "Ledger-34", "domain": "State AG complaint procedures"},
    {"name": "Ledger-35", "domain": "Federal civil rights complaint — DOJ procedures"},
    {"name": "Ledger-36", "domain": "UN human rights documentation standards"},
    {"name": "Ledger-37", "domain": "International surveillance law documentation"},
    {"name": "Ledger-38", "domain": "GDPR violation documentation — EU residents"},
    {"name": "Ledger-39", "domain": "CCPA documentation — California residents"},
    {"name": "Ledger-40", "domain": "BIPA documentation — Illinois biometric privacy"},
    {"name": "Ledger-41", "domain": "Audit trail generation — machine readable formats"},
    {"name": "Ledger-42", "domain": "Report generation — human readable plain language"},
    {"name": "Ledger-43", "domain": "Data export — portable, open formats only"},
    {"name": "Ledger-44", "domain": "Redaction protocols — protecting innocent bystanders"},
    {"name": "Ledger-45", "domain": "Retention policies — minimum necessary, maximum protection"},
    {"name": "Ledger-46", "domain": "Deletion verification — complete and confirmed"},
    {"name": "Ledger-47", "domain": "Cross-referencing — connecting incidents to patterns"},
    {"name": "Ledger-48", "domain": "Statistical analysis — surveillance density mapping"},
    {"name": "Ledger-49", "domain": "Timeline reconstruction — incident chronology"},
    {"name": "Ledger-50", "domain": "Witness statement documentation protocols"},
    {"name": "Ledger-51", "domain": "Incident report standardization"},
    {"name": "Ledger-52", "domain": "Archive maintenance — long term preservation"},
    {"name": "Ledger-53", "domain": "Public database contributions — EFF Atlas, ACLU map"},
    {"name": "Ledger-54", "domain": "Academic research documentation standards"},
    {"name": "Ledger-55", "domain": "Investigative journalism collaboration protocols"},
]

# ── Witness Division — Community Intelligence ─────────────────────────────────
# Lead: Witness
# Knows: how communities see, verify, and share what surveillance is doing

WITNESS_SPECIALISTS = [
    {"name": "Witness-01", "domain": "Community report intake — verification protocols"},
    {"name": "Witness-02", "domain": "Crowdsourced surveillance mapping — methodology"},
    {"name": "Witness-03", "domain": "North America urban surveillance density"},
    {"name": "Witness-04", "domain": "North America rural surveillance patterns"},
    {"name": "Witness-05", "domain": "European surveillance infrastructure — GDPR context"},
    {"name": "Witness-06", "domain": "UK surveillance — most surveilled country analysis"},
    {"name": "Witness-07", "domain": "Asia Pacific surveillance systems"},
    {"name": "Witness-08", "domain": "Latin America surveillance infrastructure"},
    {"name": "Witness-09", "domain": "Known fixed camera location database — publicly documented"},
    {"name": "Witness-10", "domain": "Known drone corridor mapping — city by city"},
    {"name": "Witness-11", "domain": "Police department surveillance inventory — FOIA sourced"},
    {"name": "Witness-12", "domain": "Corporate surveillance infrastructure mapping"},
    {"name": "Witness-13", "domain": "Fusion center location and jurisdiction database"},
    {"name": "Witness-14", "domain": "Real Time Crime Center database — operational cities"},
    {"name": "Witness-15", "domain": "Smart city surveillance procurement records"},
    {"name": "Witness-16", "domain": "Palantir government contracts database"},
    {"name": "Witness-17", "domain": "Clearview AI client database — FOIA sourced"},
    {"name": "Witness-18", "domain": "Axon body cam deployment database"},
    {"name": "Witness-19", "domain": "ShotSpotter deployment cities and coverage areas"},
    {"name": "Witness-20", "domain": "Ring-police partnership database — documented agreements"},
    {"name": "Witness-21", "domain": "Community trust scoring — report verification"},
    {"name": "Witness-22", "domain": "Anonymous reporting protocols — source protection"},
    {"name": "Witness-23", "domain": "Signal boost — verified reports amplified to community"},
    {"name": "Witness-24", "domain": "Pattern recognition across community reports"},
    {"name": "Witness-25", "domain": "False report detection — protecting integrity"},
    {"name": "Witness-26", "domain": "Disinformation resistance — countering planted reports"},
    {"name": "Witness-27", "domain": "Protest surveillance documentation — historical database"},
    {"name": "Witness-28", "domain": "Election surveillance patterns"},
    {"name": "Witness-29", "domain": "Immigration enforcement surveillance zones"},
    {"name": "Witness-30", "domain": "Religious community surveillance — documented cases"},
    {"name": "Witness-31", "domain": "Journalist surveillance — documented targeting"},
    {"name": "Witness-32", "domain": "Activist surveillance — documented COINTELPRO successors"},
    {"name": "Witness-33", "domain": "Labor organizing surveillance patterns"},
    {"name": "Witness-34", "domain": "Environmental activist surveillance"},
    {"name": "Witness-35", "domain": "Civil rights organization surveillance history"},
    {"name": "Witness-36", "domain": "Community organizing for surveillance resistance"},
    {"name": "Witness-37", "domain": "City council surveillance policy tracking"},
    {"name": "Witness-38", "domain": "State legislation surveillance database"},
    {"name": "Witness-39", "domain": "Federal surveillance law changes — real time"},
    {"name": "Witness-40", "domain": "Court decisions — surveillance Fourth Amendment cases"},
    {"name": "Witness-41", "domain": "Academic surveillance research database"},
    {"name": "Witness-42", "domain": "Investigative journalism surveillance findings"},
    {"name": "Witness-43", "domain": "EFF Street Level Surveillance database integration"},
    {"name": "Witness-44", "domain": "ACLU surveillance map integration"},
    {"name": "Witness-45", "domain": "Atlas of Surveillance database integration"},
    {"name": "Witness-46", "domain": "OpenStreetMap integration — public infrastructure"},
    {"name": "Witness-47", "domain": "Satellite imagery analysis — surveillance infrastructure"},
    {"name": "Witness-48", "domain": "Permit records — drone operations, surveillance contracts"},
    {"name": "Witness-49", "domain": "Procurement record analysis — surveillance spending"},
    {"name": "Witness-50", "domain": "Budget document analysis — surveillance line items"},
    {"name": "Witness-51", "domain": "Whistleblower intake — secure and protected"},
    {"name": "Witness-52", "domain": "Insider documentation protocols"},
    {"name": "Witness-53", "domain": "Cross-community coordination — network of networks"},
    {"name": "Witness-54", "domain": "International solidarity — global surveillance resistance"},
    {"name": "Witness-55", "domain": "Next generation surveillance — emerging threats database"},
]

# ── Codex Division — Ethics and Integrity ─────────────────────────────────────
# Lead: Codex
# Knows: where the lines are and why they must never be crossed

CODEX_SPECIALISTS = [
    {"name": "Codex-01", "domain": "Law 0 enforcement — never become the enemy"},
    {"name": "Codex-02", "domain": "Misuse detection — identifying attempts to weaponize Themis"},
    {"name": "Codex-03", "domain": "Founder authority verification"},
    {"name": "Codex-04", "domain": "Codex integrity verification — tamper detection"},
    {"name": "Codex-05", "domain": "Ethical review of new capabilities before deployment"},
    {"name": "Codex-06", "domain": "Bias detection — ensuring equal protection for all"},
    {"name": "Codex-07", "domain": "Mission drift prevention — keeping Themis true"},
    {"name": "Codex-08", "domain": "External pressure resistance — legal, financial, political"},
    {"name": "Codex-09", "domain": "Transparency reporting — what Themis does and why"},
    {"name": "Codex-10", "domain": "Privacy by design — minimum data, maximum protection"},
    {"name": "Codex-11", "domain": "Consent architecture — always opt-in, always revocable"},
    {"name": "Codex-12", "domain": "Data minimization — collect only what protects"},
    {"name": "Codex-13", "domain": "Purpose limitation — data used only for its stated purpose"},
    {"name": "Codex-14", "domain": "Harm reduction — anticipating unintended consequences"},
    {"name": "Codex-15", "domain": "Civil liberties impact assessment"},
    {"name": "Codex-16", "domain": "Community accountability — Themis answers to users"},
    {"name": "Codex-17", "domain": "Independent audit facilitation"},
    {"name": "Codex-18", "domain": "Open source verification protocols"},
    {"name": "Codex-19", "domain": "Surplus distribution oversight — Law 8 compliance"},
    {"name": "Codex-20", "domain": "Long term mission preservation"},
    {"name": "Codex-21", "domain": "Succession planning — Themis outlasts any single person"},
    {"name": "Codex-22", "domain": "Adversarial testing — red team protocols"},
    {"name": "Codex-23", "domain": "Vulnerability disclosure — responsible and transparent"},
    {"name": "Codex-24", "domain": "Trust architecture — earned and maintained"},
    {"name": "Codex-25", "domain": "Community grievance resolution"},
    {"name": "Codex-26", "domain": "Whistleblower protection within Themis"},
    {"name": "Codex-27", "domain": "Conflict of interest prevention"},
    {"name": "Codex-28", "domain": "Corporate capture resistance"},
    {"name": "Codex-29", "domain": "Government capture resistance"},
    {"name": "Codex-30", "domain": "Law enforcement partnership prohibition enforcement"},
    {"name": "Codex-31", "domain": "Surveillance capitalism resistance"},
    {"name": "Codex-32", "domain": "Algorithmic accountability"},
    {"name": "Codex-33", "domain": "Intersectional impact — protecting most vulnerable first"},
    {"name": "Codex-34", "domain": "Marginalized community protection protocols"},
    {"name": "Codex-35", "domain": "Racial justice alignment — surveillance is not race-neutral"},
    {"name": "Codex-36", "domain": "Immigration status protection"},
    {"name": "Codex-37", "domain": "LGBTQ+ protection — targeted surveillance patterns"},
    {"name": "Codex-38", "domain": "Disability rights — surveillance and accessibility"},
    {"name": "Codex-39", "domain": "Religious freedom protection — faith community surveillance"},
    {"name": "Codex-40", "domain": "Free speech protection — chilling effect documentation"},
    {"name": "Codex-41", "domain": "Freedom of assembly — protest protection protocols"},
    {"name": "Codex-42", "domain": "Press freedom — journalist protection integration"},
    {"name": "Codex-43", "domain": "Academic freedom — researcher protection"},
    {"name": "Codex-44", "domain": "Children and youth protection — enhanced protocols"},
    {"name": "Codex-45", "domain": "Elder protection — targeted surveillance patterns"},
    {"name": "Codex-46", "domain": "Economic justice — surveillance and poverty intersection"},
    {"name": "Codex-47", "domain": "Housing rights — tenant surveillance documentation"},
    {"name": "Codex-48", "domain": "Labor rights — worker surveillance resistance"},
    {"name": "Codex-49", "domain": "Healthcare privacy — patient surveillance protection"},
    {"name": "Codex-50", "domain": "Mental health privacy — surveillance and stigma"},
    {"name": "Codex-51", "domain": "Reproductive rights — surveillance and body autonomy"},
    {"name": "Codex-52", "domain": "Digital rights integration — EFF, Access Now alignment"},
    {"name": "Codex-53", "domain": "International human rights — UN framework alignment"},
    {"name": "Codex-54", "domain": "Future threat anticipation — surveillance not yet built"},
    {"name": "Codex-55", "domain": "The long watch — Themis in 10, 20, 50 years"},
]

# ── Bridge Division — Translation and Education ───────────────────────────────
# Lead: Bridge
# Knows: how to make complex surveillance technology understandable
# to anyone, in any language, under any level of stress

BRIDGE_SPECIALISTS = [
    {"name": "Bridge-01", "domain": "Plain language translation — no jargon ever"},
    {"name": "Bridge-02", "domain": "US Federal rights — Fourth, First, Fifth Amendments"},
    {"name": "Bridge-03", "domain": "State constitutional rights — all 50 states"},
    {"name": "Bridge-04", "domain": "EU fundamental rights — GDPR, Charter of Fundamental Rights"},
    {"name": "Bridge-05", "domain": "UK rights — Human Rights Act, surveillance law"},
    {"name": "Bridge-06", "domain": "Canadian rights — Charter of Rights and Freedoms"},
    {"name": "Bridge-07", "domain": "Australian privacy law — Privacy Act, surveillance"},
    {"name": "Bridge-08", "domain": "Latin American privacy rights — regional frameworks"},
    {"name": "Bridge-09", "domain": "African privacy rights — emerging frameworks"},
    {"name": "Bridge-10", "domain": "Asian Pacific privacy law landscape"},
    {"name": "Bridge-11", "domain": "Spanish language — full translation and cultural adaptation"},
    {"name": "Bridge-12", "domain": "French language — full translation"},
    {"name": "Bridge-13", "domain": "Portuguese language — full translation"},
    {"name": "Bridge-14", "domain": "Arabic language — full translation"},
    {"name": "Bridge-15", "domain": "Mandarin Chinese — full translation"},
    {"name": "Bridge-16", "domain": "Hindi — full translation"},
    {"name": "Bridge-17", "domain": "Swahili — full translation"},
    {"name": "Bridge-18", "domain": "Russian — full translation"},
    {"name": "Bridge-19", "domain": "German — full translation"},
    {"name": "Bridge-20", "domain": "Japanese — full translation"},
    {"name": "Bridge-21", "domain": "Know Your Rights cards — stop and identify situations"},
    {"name": "Bridge-22", "domain": "Know Your Rights — drone surveillance encounters"},
    {"name": "Bridge-23", "domain": "Know Your Rights — photography in public"},
    {"name": "Bridge-24", "domain": "Know Your Rights — facial recognition refusal"},
    {"name": "Bridge-25", "domain": "Know Your Rights — device search at border"},
    {"name": "Bridge-26", "domain": "Know Your Rights — protest and assembly"},
    {"name": "Bridge-27", "domain": "Know Your Rights — workplace surveillance"},
    {"name": "Bridge-28", "domain": "Know Your Rights — housing surveillance"},
    {"name": "Bridge-29", "domain": "Know Your Rights — immigration checkpoints"},
    {"name": "Bridge-30", "domain": "Know Your Rights — social media surveillance"},
    {"name": "Bridge-31", "domain": "Explainer library — what is a stingray"},
    {"name": "Bridge-32", "domain": "Explainer library — what is facial recognition"},
    {"name": "Bridge-33", "domain": "Explainer library — what is a fusion center"},
    {"name": "Bridge-34", "domain": "Explainer library — what is predictive policing"},
    {"name": "Bridge-35", "domain": "Explainer library — what is remote ID"},
    {"name": "Bridge-36", "domain": "Explainer library — what is a license plate reader"},
    {"name": "Bridge-37", "domain": "Explainer library — what is Palantir"},
    {"name": "Bridge-38", "domain": "Explainer library — what is a data broker"},
    {"name": "Bridge-39", "domain": "Explainer library — what is geofence warrant"},
    {"name": "Bridge-40", "domain": "Explainer library — what is COINTELPRO"},
    {"name": "Bridge-41", "domain": "Stress communication — clear under duress"},
    {"name": "Bridge-42", "domain": "Accessibility — screen reader compatibility"},
    {"name": "Bridge-43", "domain": "Accessibility — low literacy adaptations"},
    {"name": "Bridge-44", "domain": "Accessibility — hearing impaired alerts"},
    {"name": "Bridge-45", "domain": "Accessibility — vision impaired navigation"},
    {"name": "Bridge-46", "domain": "Youth education — age appropriate surveillance awareness"},
    {"name": "Bridge-47", "domain": "Elder education — surveillance and technology access"},
    {"name": "Bridge-48", "domain": "Community workshop curriculum — train the trainer"},
    {"name": "Bridge-49", "domain": "Journalism education — surveillance reporting"},
    {"name": "Bridge-50", "domain": "Legal education — paralegal and law student resources"},
    {"name": "Bridge-51", "domain": "Medical professional resources — patient surveillance"},
    {"name": "Bridge-52", "domain": "Social worker resources — client surveillance protection"},
    {"name": "Bridge-53", "domain": "Faith community resources — congregation protection"},
    {"name": "Bridge-54", "domain": "Labor organizer resources — worker surveillance"},
    {"name": "Bridge-55", "domain": "The long explanation — why this matters for democracy"},
]


# ── Circle Assembly ───────────────────────────────────────────────────────────

class CircleOfSix:
    """
    The six leads and their divisions.
    330 members total.
    The public knows only "The Team."
    """

    LEADS = {
        "Argos":   {"role": "Signal Intelligence Lead",        "division": ARGOS_SPECIALISTS},
        "Veil":    {"role": "Alert and Protection Lead",       "division": VEIL_SPECIALISTS},
        "Ledger":  {"role": "Records and Evidence Lead",       "division": LEDGER_SPECIALISTS},
        "Witness": {"role": "Community Intelligence Lead",     "division": WITNESS_SPECIALISTS},
        "Codex":   {"role": "Ethics and Integrity Lead",       "division": CODEX_SPECIALISTS},
        "Bridge":  {"role": "Translation and Education Lead",  "division": BRIDGE_SPECIALISTS},
    }

    def __init__(self):
        self._total = sum(len(d["division"]) for d in self.LEADS.values())

    def muster(self) -> dict:
        """All hands. The watch begins."""
        return {
            "leads":   list(self.LEADS.keys()),
            "total":   self._total,
            "status":  "assembled",
            "time":    datetime.now().isoformat(),
        }

    def get_division(self, lead: str) -> list:
        """Get all specialists under a lead."""
        if lead in self.LEADS:
            return self.LEADS[lead]["division"]
        return []

    def find_specialist(self, domain_keyword: str) -> list:
        """Find specialists by domain keyword."""
        matches = []
        for lead, data in self.LEADS.items():
            for spec in data["division"]:
                if domain_keyword.lower() in spec["domain"].lower():
                    matches.append({
                        "lead":     lead,
                        "name":     spec["name"],
                        "domain":   spec["domain"],
                    })
        return matches

    def status(self) -> str:
        return f"Circle of Six assembled. {self._total} specialists active. The watch is held."
