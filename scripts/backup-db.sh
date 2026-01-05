#!/bin/bash
# Backup USDA cache database
# Add to cron for weekly backups:
# 0 3 * * 0 /home/pi/slop-pi/scripts/backup-db.sh

set -e

BACKUP_DIR="/home/pi/slop-pi/backups"
DATA_DIR="/home/pi/slop-pi/data"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

# Backup USDA cache
if [ -f "$DATA_DIR/usda_cache.db" ]; then
    cp "$DATA_DIR/usda_cache.db" "$BACKUP_DIR/usda_cache_$TIMESTAMP.db"
    echo "✅ Backed up USDA cache: usda_cache_$TIMESTAMP.db"
fi

# Keep only last 4 backups
cd "$BACKUP_DIR"
ls -t usda_cache_*.db 2>/dev/null | tail -n +5 | xargs -r rm

echo "📦 Current backups:"
ls -lh "$BACKUP_DIR"
