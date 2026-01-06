# Deploying slop to Raspberry Pi (Hybrid Mode)

Run your meal planning app entirely on a Raspberry Pi with:
- **Next.js** (port 3000) - Frontend + UI
- **Python/FastAPI** (port 8000) - USDA cache, AI, cron jobs

## Why Hybrid?

| Feature | Vercel Only | Pi Hybrid |
|---------|-------------|-----------|
| USDA lookup | ~500ms (API every time) | **~10ms** (SQLite cache) |
| Cron jobs | Once/day (free tier) | Every 15 min |
| Cold starts | Yes | No |
| Offline capable | No | Partial |

## Quick Start

### 1. Copy files to your Pi

From your Mac:
```bash
# Copy Next.js app
rsync -avz --exclude 'node_modules' --exclude '.next' \
  ~/dev/xOS/xProj/ pi@YOUR_PI_IP:~/slop/

# Copy Python backend
rsync -avz --exclude '.venv' --exclude '__pycache__' --exclude '*.db' \
  ~/dev/slop-pi/ pi@YOUR_PI_IP:~/slop-pi/

# Copy env files
scp ~/dev/xOS/xProj/.env.local pi@YOUR_PI_IP:~/slop/
scp ~/dev/slop-pi/.env pi@YOUR_PI_IP:~/slop-pi/
```

### 2. Run the setup script

SSH to your Pi:
```bash
ssh pi@YOUR_PI_IP
cd ~/slop-pi/deploy
chmod +x setup-hybrid.sh
./setup-hybrid.sh
```

That's it! The script will:
- Install Node.js 20, Python/uv, PM2
- Build the Next.js app
- Start both services
- Set up cron jobs
- Configure auto-restart on boot

## Manual Setup

### Install prerequisites

```bash
# Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Python uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# PM2
sudo npm install -g pm2
```

### Build and start

```bash
# Next.js
cd ~/slop
npm install
npm run build

# Python
cd ~/slop-pi
uv sync

# Start both with PM2
pm2 start ~/ecosystem.config.js
pm2 save
pm2 startup
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Browser / Phone                                     │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│  Next.js (port 3000)                                 │
│  • Frontend UI                                       │
│  • Auth (Supabase)                                   │
│  • Most API routes                                   │
└─────────────────────┬───────────────────────────────┘
                      │ (for heavy operations)
┌─────────────────────▼───────────────────────────────┐
│  Python FastAPI (port 8000)                          │
│  • /api/usda/* - USDA with SQLite cache (85x faster)│
│  • /api/ai/* - Recipe generation                     │
│  • /api/cron/* - Scheduled jobs                      │
│  • Push notifications (ntfy.sh)                      │
└─────────────────────┬───────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────┐
│  Supabase (Cloud)                                    │
│  • PostgreSQL database                               │
│  • Auth                                              │
└─────────────────────────────────────────────────────┘
```

## Accessing Your App

| Service | URL |
|---------|-----|
| Frontend | http://YOUR_PI_IP:3000 |
| API | http://YOUR_PI_IP:8000 |
| API Docs | http://YOUR_PI_IP:8000/docs |

### Set up local hostname

Add to `/etc/hosts` on your Mac/PC:
```
YOUR_PI_IP  slop.local
```

Then access at `http://slop.local:3000`

## PM2 Commands

```bash
pm2 status              # Check both services
pm2 logs                # View all logs
pm2 logs slop-web       # Frontend logs only
pm2 logs slop-api       # Backend logs only
pm2 restart all         # Restart everything
pm2 restart slop-api    # Restart just Python
pm2 monit               # Live monitoring
```

## Updating

```bash
# Pull latest code (or rsync from Mac)
cd ~/slop && git pull
cd ~/slop-pi && git pull

# Rebuild and restart
cd ~/slop && npm install && npm run build
cd ~/slop-pi && uv sync
pm2 restart all
```

## Environment Files

### ~/slop/.env.local
```bash
NEXT_PUBLIC_SUPABASE_URL=https://xxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=xxx
SUPABASE_SERVICE_ROLE_KEY=xxx
OPENAI_API_KEY=sk-xxx
USDA_API_KEY=xxx
CRON_SECRET=xxx
```

### ~/slop-pi/.env
```bash
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=xxx
SUPABASE_SERVICE_ROLE_KEY=xxx
OPENAI_API_KEY=sk-xxx
USDA_API_KEY=xxx
CRON_SECRET=xxx
NTFY_TOPIC=your-topic  # Optional: push notifications
```

## Cron Jobs

The Python backend handles scheduled tasks via APScheduler:

| Job | Schedule | Description |
|-----|----------|-------------|
| Process consumptions | Every 15 min | Mark past meals as logged |
| Breakfast reminder | 7:30 AM | Push notification |
| Lunch reminder | 11:30 AM | Push notification |
| Dinner reminder | 5:30 PM | Push notification |
| Daily summary | 9:00 PM | Nutrition summary |

Plus a system cron as backup:
```
*/15 * * * * curl -sf http://localhost:8000/api/cron/process-consumptions
```

## Troubleshooting

### Services not starting
```bash
# Check logs
pm2 logs --lines 50

# Check ports
sudo lsof -i :3000
sudo lsof -i :8000
```

### Build fails (out of memory)
```bash
# Increase swap
sudo dphys-swapfile swapoff
sudo nano /etc/dphys-swapfile  # Set CONF_SWAPSIZE=2048
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

### Python backend errors
```bash
# Check if uv is in PATH
which uv || export PATH="$HOME/.local/bin:$PATH"

# Test manually
cd ~/slop-pi/backend
uv run uvicorn app.main:app --port 8000
```

### USDA cache not working
```bash
# Check cache stats
curl http://localhost:8000/api/usda/cache/stats

# Clear cache if corrupted
curl -X DELETE http://localhost:8000/api/usda/cache
```

## Performance Tips

1. **SQLite on SSD**: If using USB SSD, put the USDA cache there
2. **Reduce logging**: Set `LOG_LEVEL=warning` in production
3. **Memory limits**: PM2 config limits memory to prevent OOM kills
4. **Swap**: 2GB swap recommended for builds

## Future: Full Python Migration

The Python backend can eventually handle ALL API routes. To migrate more routes:

1. Implement the route in Python (`backend/app/api/`)
2. Add to Next.js `next.config.js` rewrites (optional)
3. Or have frontend call Python directly for that route

The architecture is ready - just incrementally move routes as needed.
