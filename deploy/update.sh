#!/bin/bash
#
# Quick update script for slop on Raspberry Pi
#
# Usage:
#   ./update.sh
#

set -e

SLOP_DIR="${SLOP_DIR:-$HOME/slop}"

echo "[slop] Updating..."

cd "$SLOP_DIR"

# Pull latest changes
git pull origin main

# Install any new dependencies
npm install

# Rebuild
npm run build

# Restart PM2
pm2 restart slop

echo "[slop] Update complete!"
pm2 status
