#!/bin/bash
# Deploy slop-pi to Raspberry Pi
# Usage: ./scripts/deploy.sh

set -e

echo "🍳 Deploying slop-pi..."

# Pull latest changes
echo "📥 Pulling latest changes..."
git pull origin main

# Build and start containers
echo "🐳 Building and starting containers..."
docker compose build
docker compose up -d

# Show status
echo "📊 Container status:"
docker compose ps

# Show logs
echo "📜 Recent logs:"
docker compose logs --tail=20

echo ""
echo "✅ Deployment complete!"
echo ""
echo "API:     http://slop.local:8000"
echo "Docs:    http://slop.local:8000/docs"
echo "Health:  http://slop.local:8000/health"
