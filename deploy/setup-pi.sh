#!/bin/bash
#
# Raspberry Pi Setup Script for slop
#
# Run this on your Pi to set up the entire slop application.
# Assumes Raspberry Pi OS with internet access.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/YOUR_REPO/slop-pi/main/deploy/setup-pi.sh | bash
#   # OR
#   ./setup-pi.sh
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() { echo -e "${GREEN}[slop]${NC} $1"; }
warn() { echo -e "${YELLOW}[slop]${NC} $1"; }
error() { echo -e "${RED}[slop]${NC} $1"; exit 1; }

# Configuration
SLOP_DIR="${SLOP_DIR:-$HOME/slop}"
NODE_VERSION="20"  # LTS

log "Setting up slop on Raspberry Pi..."

# ============================================
# 1. Install Node.js via nvm
# ============================================
log "Installing Node.js ${NODE_VERSION}..."

if ! command -v node &> /dev/null; then
    # Install nvm
    if [ ! -d "$HOME/.nvm" ]; then
        curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
    fi

    # Load nvm
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

    # Install Node.js
    nvm install $NODE_VERSION
    nvm use $NODE_VERSION
    nvm alias default $NODE_VERSION
else
    log "Node.js already installed: $(node --version)"
fi

# ============================================
# 2. Install PM2 globally
# ============================================
log "Installing PM2..."
npm install -g pm2

# ============================================
# 3. Clone or update the repository
# ============================================
if [ -d "$SLOP_DIR" ]; then
    log "Updating existing slop installation..."
    cd "$SLOP_DIR"
    git pull origin main || warn "Git pull failed - continuing with existing code"
else
    log "Cloning slop repository..."
    # Replace with your actual repo URL
    git clone https://github.com/YOUR_USERNAME/xProj.git "$SLOP_DIR" || error "Failed to clone repository"
    cd "$SLOP_DIR"
fi

# ============================================
# 4. Install dependencies
# ============================================
log "Installing dependencies..."
npm install

# ============================================
# 5. Create .env.local if it doesn't exist
# ============================================
if [ ! -f "$SLOP_DIR/.env.local" ]; then
    warn ".env.local not found. Creating template..."
    cat > "$SLOP_DIR/.env.local" << 'EOF'
# Supabase Configuration (REQUIRED)
NEXT_PUBLIC_SUPABASE_URL=https://bbnsnlqtzmykbgsvpgdb.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=YOUR_ANON_KEY_HERE

# Supabase Service Role Key (SERVER-SIDE ONLY)
SUPABASE_SERVICE_ROLE_KEY=YOUR_SERVICE_ROLE_KEY_HERE

# OpenAI API Key
OPENAI_API_KEY=sk-YOUR_KEY_HERE

# USDA API Key
USDA_API_KEY=YOUR_USDA_KEY_HERE

# Cron Secret (generate with: openssl rand -base64 32)
CRON_SECRET=YOUR_CRON_SECRET_HERE

# Optional: Resend for emails
# RESEND_API_KEY=re_YOUR_KEY_HERE
# RESEND_FROM_EMAIL=slop <noreply@yourdomain.com>

# Optional: Admin UUID
# FOODOS2_ADMIN_UUID=YOUR_UUID_HERE
EOF
    warn "Please edit $SLOP_DIR/.env.local with your actual keys!"
    warn "Then re-run this script."
    exit 0
fi

# ============================================
# 6. Create logs directory
# ============================================
mkdir -p "$SLOP_DIR/logs"

# ============================================
# 7. Build the application
# ============================================
log "Building Next.js application..."
npm run build

# ============================================
# 8. Set up PM2
# ============================================
log "Setting up PM2..."

# Create PM2 ecosystem config
cat > "$SLOP_DIR/ecosystem.config.js" << 'EOF'
module.exports = {
  apps: [{
    name: 'slop',
    script: 'npm',
    args: 'start',
    cwd: process.env.HOME + '/slop',
    instances: 1,
    autorestart: true,
    watch: false,
    max_memory_restart: '512M',
    env: {
      NODE_ENV: 'production',
      PORT: 3000,
    },
    error_file: './logs/error.log',
    out_file: './logs/out.log',
    merge_logs: true,
    log_date_format: 'YYYY-MM-DD HH:mm:ss',
  }],
};
EOF

# Start with PM2
pm2 start "$SLOP_DIR/ecosystem.config.js"

# Save PM2 process list
pm2 save

# Set up PM2 to start on boot
pm2 startup | tail -1 | bash || warn "PM2 startup setup may need manual intervention"

# ============================================
# 9. Set up cron jobs
# ============================================
log "Setting up cron jobs..."

# Get CRON_SECRET from .env.local
CRON_SECRET=$(grep "^CRON_SECRET=" "$SLOP_DIR/.env.local" | cut -d'=' -f2)

if [ -z "$CRON_SECRET" ] || [ "$CRON_SECRET" = "YOUR_CRON_SECRET_HERE" ]; then
    # Generate a new cron secret
    CRON_SECRET=$(openssl rand -base64 32)
    sed -i "s/CRON_SECRET=.*/CRON_SECRET=$CRON_SECRET/" "$SLOP_DIR/.env.local"
    log "Generated new CRON_SECRET"
fi

# Create cron jobs
CRON_JOBS=$(cat << EOF
# slop cron jobs - auto-generated
# Process meal consumptions every 15 minutes
*/15 * * * * curl -s -H "Authorization: Bearer $CRON_SECRET" http://localhost:3000/api/cron/process-consumptions >> $SLOP_DIR/logs/cron.log 2>&1

# Optional: Daily cleanup at midnight
# 0 0 * * * curl -s -H "Authorization: Bearer $CRON_SECRET" http://localhost:3000/api/cron/daily-cleanup >> $SLOP_DIR/logs/cron.log 2>&1
EOF
)

# Add cron jobs (removing old slop entries first)
(crontab -l 2>/dev/null | grep -v "slop" || true; echo "$CRON_JOBS") | crontab -

# ============================================
# 10. Set up local hostname (optional)
# ============================================
log "Configuring local hostname..."

# Add slop.local to /etc/hosts if not present
if ! grep -q "slop.local" /etc/hosts 2>/dev/null; then
    echo "127.0.0.1 slop.local" | sudo tee -a /etc/hosts > /dev/null
fi

# ============================================
# Done!
# ============================================
echo ""
log "========================================="
log "slop is now running on your Raspberry Pi!"
log "========================================="
echo ""
log "Access your app at:"
log "  http://$(hostname -I | awk '{print $1}'):3000"
log "  http://slop.local:3000 (if mDNS works)"
echo ""
log "Useful commands:"
log "  pm2 status        - Check if slop is running"
log "  pm2 logs slop     - View application logs"
log "  pm2 restart slop  - Restart the application"
log "  pm2 stop slop     - Stop the application"
echo ""
log "Cron jobs are running every 15 minutes."
log "Logs are in: $SLOP_DIR/logs/"
echo ""
