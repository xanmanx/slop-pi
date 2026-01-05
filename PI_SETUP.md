# Raspberry Pi Setup for slop-pi

You are helping set up a Raspberry Pi to run **slop** - a meal planning and nutrition tracking app. This Pi will run a Python FastAPI backend that connects to a cloud Supabase database.

## System Requirements

- Raspberry Pi 4 or 5 (4GB+ RAM recommended)
- Raspberry Pi OS (64-bit recommended)
- Connected to home network with static IP or DHCP reservation

## Step 1: System Update & Core Dependencies

```bash
sudo apt update && sudo apt upgrade -y

# Essential build tools
sudo apt install -y \
  git \
  curl \
  wget \
  build-essential \
  libffi-dev \
  libssl-dev \
  python3-dev \
  python3-pip \
  python3-venv \
  sqlite3 \
  nginx \
  avahi-daemon \
  avahi-utils
```

## Step 2: Install Docker (for containerized deployment)

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add pi user to docker group
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt install -y docker-compose-plugin

# Start Docker on boot
sudo systemctl enable docker

# Log out and back in for group changes to take effect
# Or run: newgrp docker
```

Verify Docker:
```bash
docker --version
docker compose version
```

## Step 3: Install uv (Fast Python Package Manager)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

Verify:
```bash
uv --version
```

## Step 4: Set Up mDNS (Access via slop.local)

The Pi should already have avahi-daemon from Step 1. Configure hostname:

```bash
# Set hostname to 'slop'
sudo hostnamectl set-hostname slop

# Edit /etc/hosts to match
sudo sed -i 's/127.0.1.1.*/127.0.1.1\tslop/' /etc/hosts

# Restart avahi
sudo systemctl restart avahi-daemon
```

After reboot, the Pi will be accessible at `slop.local` from any device on your network.

## Step 5: Create App Directory Structure

```bash
mkdir -p ~/slop-pi/{backend,data,logs,backups}
cd ~/slop-pi
```

## Step 6: Configure Swap (Important for Pi 4 with 4GB or less)

```bash
# Increase swap for build processes
sudo dphys-swapfile swapoff
sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

## Step 7: Set Up Firewall

```bash
sudo apt install -y ufw

# Allow SSH, HTTP, HTTPS, and the API port
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 8000/tcp  # FastAPI
sudo ufw allow 3000/tcp  # Next.js (if running frontend on Pi)
sudo ufw allow 5353/udp  # mDNS

sudo ufw enable
```

## Step 8: Install Node.js (for Next.js frontend, optional)

Only needed if running the frontend on the Pi:

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

## Step 9: Set Up Cron Job Infrastructure

```bash
# Ensure cron is running
sudo systemctl enable cron
sudo systemctl start cron

# Create a logs directory for cron output
mkdir -p ~/slop-pi/logs/cron
```

## Step 10: Create Environment File Template

```bash
cat > ~/slop-pi/.env.template << 'EOF'
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key

# USDA FoodData Central API
USDA_API_KEY=your-usda-api-key

# OpenAI
OPENAI_API_KEY=your-openai-api-key

# Notifications (optional - ntfy.sh)
NTFY_TOPIC=your-private-topic
NTFY_SERVER=https://ntfy.sh

# App Config
API_HOST=0.0.0.0
API_PORT=8000
ENVIRONMENT=production
LOG_LEVEL=info

# Cron Secret (for authenticated cron endpoints)
CRON_SECRET=generate-a-random-string-here
EOF
```

Copy to actual .env and fill in values:
```bash
cp ~/slop-pi/.env.template ~/slop-pi/.env
nano ~/slop-pi/.env
```

## Step 11: System Optimizations for Pi

```bash
# Reduce GPU memory (headless server doesn't need it)
echo "gpu_mem=16" | sudo tee -a /boot/config.txt

# Disable unnecessary services
sudo systemctl disable bluetooth
sudo systemctl disable hciuart

# Enable hardware watchdog (auto-reboot on hang)
echo "dtparam=watchdog=on" | sudo tee -a /boot/config.txt
sudo apt install -y watchdog
sudo systemctl enable watchdog
```

## Step 12: Set Up Log Rotation

```bash
sudo cat > /etc/logrotate.d/slop-pi << 'EOF'
/home/pi/slop-pi/logs/*.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    create 0640 pi pi
}
EOF
```

## Step 13: Reboot and Verify

```bash
sudo reboot
```

After reboot, verify:
```bash
# Check hostname
hostname  # Should show: slop

# Check Docker
docker ps

# Check mDNS (from another device on network)
# ping slop.local

# Check Python
python3 --version
uv --version
```

## Ready for Deployment

The Pi is now ready to receive the slop-pi application. The deployment will:

1. Clone the repo to `~/slop-pi/backend`
2. Use Docker Compose to run:
   - FastAPI backend (port 8000)
   - SQLite for local USDA cache
   - Scheduled cron jobs
3. Optionally run Next.js frontend (or proxy to Vercel)

## Quick Reference

| Service | URL |
|---------|-----|
| API | http://slop.local:8000 |
| API Docs | http://slop.local:8000/docs |
| Frontend | http://slop.local:3000 (if local) |
| Health Check | http://slop.local:8000/health |

## Network Info Commands

```bash
# Get Pi's IP address
hostname -I

# Check what's listening
sudo lsof -i -P -n | grep LISTEN

# Test mDNS
avahi-resolve-host-name slop.local
```

## Troubleshooting

### Can't access slop.local
```bash
sudo systemctl restart avahi-daemon
```

### Docker permission denied
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### Out of memory during builds
```bash
# Check swap
free -h

# Increase swap if needed
sudo dphys-swapfile swapoff
sudo sed -i 's/CONF_SWAPSIZE=.*/CONF_SWAPSIZE=4096/' /etc/dphys-swapfile
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```
