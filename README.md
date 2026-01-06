# slop-pi v2.0

FastAPI backend for **slop** - a meal planning & nutrition tracking app, optimized for Raspberry Pi deployment.

**v2.0 Features:**
- Comprehensive micronutrient tracking with RDA percentages
- Recipe DAG flattening with full nutrition computation
- Nutrition analytics and trend analysis
- Heavy computation offloaded from frontend
- Aggressive caching for fast responses

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
│  • Recipe flattening with DAG traversal                      │
│  • Comprehensive nutrition analytics                         │
│  • RDA tracking for 20+ micronutrients                       │
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

### Core Features
- **USDA FoodData Central** with local SQLite cache - first lookup hits USDA API, subsequent lookups are instant
- **Recipe DAG Flattening** - traverse nested meal structures and compute total nutrition with caching
- **Comprehensive Nutrition Analytics** - daily/weekly stats with RDA tracking, trends, and scores
- **AI-powered recipe generation** using OpenAI (gpt-4o-mini for quick, gpt-4o for complex)
- **Scheduled jobs** for processing meal consumptions and sending reminders
- **Push notifications** via ntfy.sh for meal reminders and daily summaries

### Micronutrient Tracking
- 20+ vitamins and minerals tracked with RDA percentages
- Status indicators: deficient, low, adequate, excess
- Vitamin and mineral scores per day
- Deficiency detection and alerts

### Performance Optimizations
- Recipe graph caching (5 min TTL)
- Flattened recipe caching (10 min TTL)
- Batch operations for multiple recipes
- Parallel database queries
- Multi-worker deployment for Pi

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

### Health
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Basic health check |
| `/health/detailed` | GET | System stats (CPU, RAM, temp) |

### Nutrition (NEW in v2.0)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/nutrition/daily/{user_id}` | GET | Daily nutrition with RDA tracking |
| `/api/nutrition/weekly/{user_id}` | GET | Weekly analytics and trends |
| `/api/nutrition/analytics/{user_id}` | GET | Custom date range analytics |
| `/api/nutrition/rda` | GET | RDA reference data |

### Recipes (NEW in v2.0)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/recipes/flatten` | POST | Flatten recipe with full nutrition |
| `/api/recipes/flatten/{id}` | GET | Flatten recipe (GET method) |
| `/api/recipes/flatten/batch` | POST | Flatten multiple recipes in parallel |
| `/api/recipes/cache` | DELETE | Clear recipe caches |
| `/api/recipes/cache/stats` | GET | Cache statistics |

### USDA
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/usda/search` | GET | Search USDA foods (cached) |
| `/api/usda/food/{fdc_id}` | GET | Get specific food |
| `/api/usda/hydrate` | POST | Import to Supabase |
| `/api/usda/cache/stats` | GET | Cache statistics |

### AI
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ai/recipe` | POST | Generate recipe |
| `/api/ai/lookup` | POST | Lookup nutrition |
| `/api/ai/batch-prep` | POST | Generate batch prep plan |

### Cron Jobs
| Endpoint | Method | Description |
|----------|--------|-------------|
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

## Systemd Deployment (Alternative to Docker)

```bash
# Copy service file
sudo cp deploy/slop-pi.service /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable slop-pi
sudo systemctl start slop-pi

# Check status
sudo systemctl status slop-pi

# View logs
journalctl -u slop-pi -f
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

## Frontend Integration

### Environment Variable

Add to your Next.js `.env.local`:

```bash
NEXT_PUBLIC_SLOP_PI_URL=http://slop.local:8000
```

### Using the API Client

```typescript
import { getSlopPiClient } from '@/lib/foodos2/api-client'

// Get daily nutrition
const client = getSlopPiClient()
const dailyStats = await client.getDailyNutrition(userId, '2024-01-15')

console.log(dailyStats.nutrition.macros.calories)
console.log(dailyStats.vitamin_score)  // 0-100
console.log(dailyStats.mineral_score)  // 0-100

// Flatten a recipe
const recipe = await client.flattenRecipe(recipeId, userId, 1.0)
console.log(recipe.nutrition.top_micronutrients)

// Batch flatten for a day's meals
const recipes = await client.flattenRecipesBatch(recipeIds, userId)
```

### Using React Hooks

```typescript
import {
  useDailyNutritionFromBackend,
  useRecipeFlattenedFromBackend,
} from '@/app/slop/_data/useNutritionFromBackend'

function DayStats({ userId, date }: { userId: string; date: string }) {
  const { nutrition, isLoading, error } = useDailyNutritionFromBackend(userId, date)

  if (isLoading) return <Loading />
  if (!nutrition) return <div>No data</div>

  return (
    <div>
      <h2>Calories: {nutrition.nutrition.macros.calories}</h2>
      <h3>Vitamin Score: {nutrition.vitamin_score}%</h3>
      <h3>Mineral Score: {nutrition.mineral_score}%</h3>

      {nutrition.nutrition.micronutrients.map((m) => (
        <div key={m.nutrient_id}>
          {m.name}: {m.amount.toFixed(1)}{m.unit} ({m.percent_rda?.toFixed(0)}% RDA)
          {m.status === 'deficient' && <span>⚠️ Low</span>}
        </div>
      ))}
    </div>
  )
}
```

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

## Performance

On Raspberry Pi 4 (4GB):
- Recipe flattening: ~50-100ms (cached: ~5ms)
- Daily nutrition: ~200ms
- Weekly analytics: ~800ms
- USDA search (cached): ~10ms
- Memory usage: ~150-250MB

## License

MIT
