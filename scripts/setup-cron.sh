#!/bin/bash
# Set up system crontab for slop-pi
# Run this once after deployment

set -e

CRON_FILE="/tmp/slop-cron"

echo "Setting up cron jobs for slop-pi..."

# Create cron entries
cat > "$CRON_FILE" << EOF
# slop-pi cron jobs
# Process scheduled meal consumptions every 15 minutes
*/15 * * * * curl -s http://localhost:8000/api/cron/process-consumptions >> $HOME/slop-pi/logs/cron.log 2>&1

# Meal reminders (30 min before typical meal times)
30 7 * * * curl -s http://localhost:8000/api/cron/meal-reminders >> $HOME/slop-pi/logs/cron.log 2>&1
30 11 * * * curl -s http://localhost:8000/api/cron/meal-reminders >> $HOME/slop-pi/logs/cron.log 2>&1
30 17 * * * curl -s http://localhost:8000/api/cron/meal-reminders >> $HOME/slop-pi/logs/cron.log 2>&1

# Daily summary at 9 PM
0 21 * * * curl -s http://localhost:8000/api/cron/daily-summary >> $HOME/slop-pi/logs/cron.log 2>&1

# Rotate cron log weekly
0 0 * * 0 find $HOME/slop-pi/logs -name "cron.log" -size +10M -exec truncate -s 0 {} \;
EOF

# Install crontab
crontab "$CRON_FILE"
rm "$CRON_FILE"

echo "✅ Cron jobs installed:"
crontab -l | grep -v "^#" | grep -v "^$"
