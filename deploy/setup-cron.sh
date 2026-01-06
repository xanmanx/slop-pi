#!/bin/bash
#
# Set up cron jobs for slop on Raspberry Pi
#
# Replaces Vercel Cron with system crontab
#
# Usage:
#   ./setup-cron.sh
#

set -e

SLOP_DIR="${SLOP_DIR:-$HOME/slop}"

# Get CRON_SECRET from .env.local
if [ -f "$SLOP_DIR/.env.local" ]; then
    CRON_SECRET=$(grep "^CRON_SECRET=" "$SLOP_DIR/.env.local" | cut -d'=' -f2)
fi

if [ -z "$CRON_SECRET" ]; then
    echo "[slop] ERROR: CRON_SECRET not found in $SLOP_DIR/.env.local"
    echo "[slop] Please add: CRON_SECRET=your-secret-here"
    exit 1
fi

echo "[slop] Setting up cron jobs..."

# Create logs directory
mkdir -p "$SLOP_DIR/logs"

# Define cron jobs
CRON_JOBS="
# ============================================
# slop cron jobs
# ============================================

# Process meal consumptions every 15 minutes
*/15 * * * * curl -sf -H \"Authorization: Bearer $CRON_SECRET\" http://localhost:3000/api/cron/process-consumptions >> $SLOP_DIR/logs/cron.log 2>&1

# Log rotation - clear old logs weekly
0 0 * * 0 find $SLOP_DIR/logs -name '*.log' -mtime +7 -delete 2>/dev/null
"

# Remove existing slop cron entries and add new ones
(crontab -l 2>/dev/null | grep -v "slop" | grep -v "process-consumptions" || true; echo "$CRON_JOBS") | crontab -

echo "[slop] Cron jobs installed:"
crontab -l | grep -A5 "slop cron jobs" || echo "(no jobs found)"

echo ""
echo "[slop] Done! Cron is now processing consumptions every 15 minutes."
echo "[slop] Logs: $SLOP_DIR/logs/cron.log"
