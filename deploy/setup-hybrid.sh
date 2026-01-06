#!/bin/bash
#
# Hybrid Setup Script for slop on Raspberry Pi
#
# Runs BOTH:
#   - Next.js frontend (port 3000)
#   - Python backend (port 8000) with USDA cache, AI, cron
#
# Usage:
#   ./setup-hybrid.sh
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[slop]${NC} $1"; }
warn() { echo -e "${YELLOW}[slop]${NC} $1"; }
info() { echo -e "${BLUE}[slop]${NC} $1"; }
error() { echo -e "${RED}[slop]${NC} $1"; exit 1; }

# Configuration
SLOP_DIR="${SLOP_DIR:-$HOME/slop}"
SLOP_PI_DIR="${SLOP_PI_DIR:-$HOME/slop-pi}"
NODE_VERSION="20"

log "============================================="
log "  slop Hybrid Setup for Raspberry Pi"
log "============================================="
echo ""

# ============================================
# 1. Check if running on Pi
# ============================================
if [[ "$(uname -m)" == "aarch64" ]] || [[ "$(uname -m)" == "armv7l" ]]; then
    log "Detected Raspberry Pi ($(uname -m))"
else
    warn "Not running on Pi ($(uname -m)) - proceeding anyway for testing"
fi

# ============================================
# 2. Install Node.js
# ============================================
log "Checking Node.js..."

if command -v node &> /dev/null; then
    NODE_VER=$(node --version)
    log "Node.js already installed: $NODE_VER"
else
    log "Installing Node.js ${NODE_VERSION}..."
    curl -fsSL https://deb.nodesource.com/setup_${NODE_VERSION}.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi

# ============================================
# 3. Install Python/uv
# ============================================
log "Checking Python/uv..."

if command -v uv &> /dev/null; then
    log "uv already installed: $(uv --version)"
else
    log "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# ============================================
# 4. Install PM2
# ============================================
log "Installing PM2..."
sudo npm install -g pm2 2>/dev/null || npm install -g pm2

# ============================================
# 5. Setup directories
# ============================================
log "Setting up directories..."

mkdir -p "$SLOP_DIR/logs"
mkdir -p "$SLOP_PI_DIR/logs"
mkdir -p "$SLOP_PI_DIR/backend/data"

# ============================================
# 6. Check for required files
# ============================================
if [ ! -d "$SLOP_DIR" ]; then
    error "Next.js app not found at $SLOP_DIR"
fi

if [ ! -d "$SLOP_PI_DIR" ]; then
    error "Python backend not found at $SLOP_PI_DIR"
fi

if [ ! -f "$SLOP_DIR/.env.local" ]; then
    warn ".env.local not found in $SLOP_DIR"
    warn "Please copy your environment file before continuing"
fi

if [ ! -f "$SLOP_PI_DIR/.env" ]; then
    warn ".env not found in $SLOP_PI_DIR"
    warn "Please copy your environment file before continuing"
fi

# ============================================
# 7. Install dependencies
# ============================================
log "Installing Next.js dependencies..."
cd "$SLOP_DIR"
npm install

log "Installing Python dependencies..."
cd "$SLOP_PI_DIR"
uv sync

# ============================================
# 8. Build Next.js
# ============================================
log "Building Next.js app..."
cd "$SLOP_DIR"
npm run build

# ============================================
# 9. Create PM2 ecosystem config
# ============================================
log "Creating PM2 config..."

cat > "$HOME/ecosystem.config.js" << EOF
module.exports = {
  apps: [
    {
      name: 'slop-web',
      cwd: '$SLOP_DIR',
      script: 'npm',
      args: 'start',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '400M',
      env: {
        NODE_ENV: 'production',
        PORT: 3000,
      },
      error_file: '$SLOP_DIR/logs/web-error.log',
      out_file: '$SLOP_DIR/logs/web-out.log',
      merge_logs: true,
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
    },
    {
      name: 'slop-api',
      cwd: '$SLOP_PI_DIR/backend',
      script: '$HOME/.local/bin/uv',
      args: 'run uvicorn app.main:app --host 0.0.0.0 --port 8000',
      interpreter: 'none',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '256M',
      env: {
        ENVIRONMENT: 'production',
      },
      error_file: '$SLOP_PI_DIR/logs/api-error.log',
      out_file: '$SLOP_PI_DIR/logs/api-out.log',
      merge_logs: true,
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
    },
  ],
}
EOF

# ============================================
# 10. Start services with PM2
# ============================================
log "Starting services..."

pm2 delete all 2>/dev/null || true
pm2 start "$HOME/ecosystem.config.js"
pm2 save

# Setup PM2 startup
log "Setting up PM2 startup..."
pm2 startup 2>/dev/null | tail -1 | bash 2>/dev/null || warn "Run 'pm2 startup' manually if needed"

# ============================================
# 11. Setup cron jobs
# ============================================
log "Setting up cron jobs..."

# Get CRON_SECRET
CRON_SECRET=""
if [ -f "$SLOP_PI_DIR/.env" ]; then
    CRON_SECRET=$(grep "^CRON_SECRET=" "$SLOP_PI_DIR/.env" | cut -d'=' -f2 | tr -d '"')
fi

if [ -z "$CRON_SECRET" ]; then
    CRON_SECRET=$(openssl rand -base64 32)
    echo "CRON_SECRET=\"$CRON_SECRET\"" >> "$SLOP_PI_DIR/.env"
    log "Generated new CRON_SECRET"
fi

CRON_JOBS="
# slop cron jobs - process consumptions every 15 min
*/15 * * * * curl -sf http://localhost:8000/api/cron/process-consumptions >> $SLOP_PI_DIR/logs/cron.log 2>&1
"

(crontab -l 2>/dev/null | grep -v "slop" | grep -v "process-consumptions" || true; echo "$CRON_JOBS") | crontab -

# ============================================
# 12. Wait and verify
# ============================================
log "Waiting for services to start..."
sleep 5

echo ""
log "============================================="
log "  Verifying services..."
log "============================================="

# Check Python backend
if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    log "✓ Python backend (port 8000) - RUNNING"
else
    warn "✗ Python backend (port 8000) - NOT RESPONDING"
fi

# Check Next.js
if curl -sf http://localhost:3000 > /dev/null 2>&1; then
    log "✓ Next.js frontend (port 3000) - RUNNING"
else
    warn "✗ Next.js frontend (port 3000) - NOT RESPONDING (may still be starting)"
fi

# ============================================
# Done!
# ============================================
echo ""
log "============================================="
log "  slop is running!"
log "============================================="
echo ""
info "Frontend:  http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):3000"
info "API:       http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):8000"
info "API Docs:  http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):8000/docs"
echo ""
info "Commands:"
info "  pm2 status        - Check service status"
info "  pm2 logs          - View all logs"
info "  pm2 logs slop-web - View frontend logs"
info "  pm2 logs slop-api - View backend logs"
info "  pm2 restart all   - Restart everything"
echo ""
info "Logs:"
info "  Frontend: $SLOP_DIR/logs/"
info "  Backend:  $SLOP_PI_DIR/logs/"
echo ""
