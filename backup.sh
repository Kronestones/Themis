#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════════
# backup.sh — Themis Full Safe Save
#
# Backs up:
#   1. map.html          — the live map template
#   2. database.py       — the database code
#   3. Neon DB dump      — all live PostgreSQL data (infrastructure + detections)
#   4. Git snapshot      — commits everything to the repo with a timestamped tag
#
# Usage:
#   cd ~/themis_gaia
#   bash backup.sh
#
# Restore DB from backup:
#   psql $DATABASE_URL < ~/themis_backups/themis_db_YYYYMMDD_HHMMSS.sql
# ══════════════════════════════════════════════════════════════════════════════

set -e  # Stop on any error

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$HOME/themis_backups"
REPO_DIR="$HOME/themis_gaia"
BACKUP_LABEL="themis_backup_$TIMESTAMP"

echo ""
echo "⚖  THEMIS SAFE SAVE — $TIMESTAMP"
echo "════════════════════════════════════════"

# ── 1. Create backup directory ────────────────────────────────────────────────
mkdir -p "$BACKUP_DIR"
echo "📁 Backup dir: $BACKUP_DIR"

# ── 2. Back up map.html ───────────────────────────────────────────────────────
MAP_SRC="$REPO_DIR/themis/templates/map.html"
MAP_DEST="$BACKUP_DIR/map_$TIMESTAMP.html"

if [ -f "$MAP_SRC" ]; then
    cp "$MAP_SRC" "$MAP_DEST"
    echo "✅ map.html → $MAP_DEST"
else
    echo "⚠️  map.html not found at $MAP_SRC — skipping"
fi

# ── 3. Back up database.py ────────────────────────────────────────────────────
DB_SRC="$REPO_DIR/themis/database.py"
DB_DEST="$BACKUP_DIR/database_$TIMESTAMP.py"

if [ -f "$DB_SRC" ]; then
    cp "$DB_SRC" "$DB_DEST"
    echo "✅ database.py → $DB_DEST"
else
    echo "⚠️  database.py not found at $DB_SRC — skipping"
fi

# ── 4. Dump live Neon PostgreSQL database ─────────────────────────────────────
SQL_DEST="$BACKUP_DIR/themis_db_$TIMESTAMP.sql"

if [ -z "$DATABASE_URL" ]; then
    # Try to load from .env if it exists
    if [ -f "$REPO_DIR/.env" ]; then
        export $(grep -v '^#' "$REPO_DIR/.env" | xargs)
    fi
fi

if [ -z "$DATABASE_URL" ]; then
    echo "⚠️  DATABASE_URL not set — skipping database dump"
    echo "   Set it with: export DATABASE_URL=your_neon_connection_string"
else
    echo "📦 Dumping Neon database..."
    if pg_dump "$DATABASE_URL" > "$SQL_DEST" 2>/dev/null; then
        SIZE=$(du -h "$SQL_DEST" | cut -f1)
        echo "✅ Database dump → $SQL_DEST ($SIZE)"
    else
        echo "⚠️  pg_dump failed — you may need to install it:"
        echo "   pkg install postgresql"
        rm -f "$SQL_DEST"
    fi
fi

# ── 5. Git snapshot — commit + tag ───────────────────────────────────────────
echo ""
echo "📌 Creating git snapshot..."
cd "$REPO_DIR"

# Stage any uncommitted changes
git add -A

# Only commit if there's something to commit
if ! git diff --cached --quiet; then
    git commit -m "Safe save backup — $TIMESTAMP"
    echo "✅ Git commit created"
else
    echo "ℹ️  No uncommitted changes — skipping commit"
fi

# Create a lightweight tag so you can always return to this exact state
git tag "backup/$TIMESTAMP"
echo "✅ Git tag: backup/$TIMESTAMP"

# Push everything
git push origin main --tags
echo "✅ Pushed to GitHub"

# ── 6. Summary ────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════"
echo "⚖  BACKUP COMPLETE — $TIMESTAMP"
echo ""
echo "Files saved to $BACKUP_DIR:"
ls -lh "$BACKUP_DIR" | grep "$TIMESTAMP" | awk '{print "   " $NF " (" $5 ")"}'
echo ""
echo "To restore database if needed:"
echo "   psql \$DATABASE_URL < $SQL_DEST"
echo ""
echo "To return to this git state:"
echo "   git checkout backup/$TIMESTAMP"
echo "════════════════════════════════════════"
