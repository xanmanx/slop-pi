# slop-pi

FastAPI backend for **slop** - a meal planning & nutrition tracking app, optimized for Raspberry Pi deployment.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│           Your Phone/Browser (slop frontend)                │
│              Next.js @ Vercel or slop.local:3000             │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│              slop-pi (this repo)                             │
│              FastAPI on Raspberry Pi                         │
│                                                              │
│  • USDA API + SQLite cache (instant lookups)                 │
│  • AI: recipe generation, nutrition lookup                   │
│  • Cron: consumption processing, meal reminders              │
│  • Push notifications via ntfy.sh                            │
└───────────────────────┬─────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────┐
│              Supabase (PostgreSQL)                           │
│              Cloud database for all app data                 │
└─────────────────────────────────────────────────────────────┘
```

## Features

- **USDA FoodData Central** with local SQLite cache - first lookup hits USDA API, subsequent lookups are instant
- **AI-powered recipe generation** using OpenAI (gpt-4o-mini for quick, gpt-4o for complex)
- **Scheduled jobs** for processing meal consumptions and sending reminders
- **Push notifications** via ntfy.sh for meal reminders and daily summaries
- **Health monitoring** endpoint with CPU, memory, disk, and temperature stats

## Quick Start

### 1. Prepare Your Pi

Follow [PI_SETUP.md](./PI_SETUP.md) to set up your Raspberry Pi.

### 2. Clone & Configure

```bash
cd ~
git clone https://github.com/yourusername/slop-pi.git
cd slop-pi

# Copy and edit environment variables
cp .env.example .env
nano .env  # Fill in your keys
```

### 3. Deploy

```bash
# Make scripts executable
chmod +x scripts/*.sh

# Deploy with Docker
./scripts/deploy.sh

# Set up cron jobs
./scripts/setup-cron.sh
```

### 4. Verify

```bash
# Health check
curl http://slop.local:8000/health

# API docs
open http://slop.local:8000/docs
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Basic health check |
| `/health/detailed` | GET | System stats (CPU, RAM, temp) |
| `/api/usda/search` | GET | Search USDA foods (cached) |
| `/api/usda/food/{fdc_id}` | GET | Get specific food |
| `/api/usda/hydrate` | POST | Import to Supabase |
| `/api/usda/cache/stats` | GET | Cache statistics |
| `/api/ai/recipe` | POST | Generate recipe |
| `/api/ai/lookup` | POST | Lookup nutrition |
| `/api/ai/batch-prep` | POST | Generate batch prep plan |
| `/api/cron/process-consumptions` | GET | Process scheduled meals |
| `/api/cron/meal-reminders` | GET | Send meal reminders |

## Development

### Local Setup (without Docker)

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create venv and install
cd /path/to/slop-pi
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# Copy env
cp .env.example .env
# Edit .env with your keys

# Run
cd backend
uvicorn app.main:app --reload
```

### Running Tests

```bash
pytest
```

## Notifications

slop-pi uses [ntfy.sh](https://ntfy.sh) for push notifications. To set up:

1. Go to ntfy.sh and pick a unique topic name
2. Subscribe to it on your phone (iOS/Android app)
3. Add `NTFY_TOPIC=your-topic-name` to `.env`

You'll get notifications for:
- Meal reminders (30 min before each meal)
- Daily nutrition summaries (9 PM)
- Grocery shopping reminders

## Cron Jobs

The scheduler runs these jobs automatically:

| Job | Schedule | Description |
|-----|----------|-------------|
| Process consumptions | Every 15 min | Mark past meals as consumed |
| Breakfast reminder | 7:30 AM | Notify about breakfast |
| Lunch reminder | 11:30 AM | Notify about lunch |
| Dinner reminder | 5:30 PM | Notify about dinner |
| Daily summary | 9:00 PM | Send nutrition summary |

You can also trigger them via the API or system crontab (see `scripts/setup-cron.sh`).

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_ANON_KEY` | Yes | Supabase anon key |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | Supabase service role key |
| `USDA_API_KEY` | Yes | USDA FoodData Central API key |
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `NTFY_TOPIC` | No | ntfy.sh topic for notifications |
| `CRON_SECRET` | No | Secret for authenticating cron endpoints |

## Updating

```bash
cd ~/slop-pi
git pull
./scripts/deploy.sh
```

Or enable Watchtower for auto-updates:

```bash
docker compose --profile auto-update up -d
```

## Connecting the Frontend

Update your Next.js app to use the Pi backend for API calls:

```typescript
// In your frontend, set the API base URL
const API_BASE = process.env.NEXT_PUBLIC_PI_API_URL || 'http://slop.local:8000'

// Example: Search USDA
const response = await fetch(`${API_BASE}/api/usda/search?query=chicken`)
```

## License

MIT
