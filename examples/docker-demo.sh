#!/usr/bin/env bash
# docker-demo.sh — Launch Trellis stack and run the demo against it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "🚀 Starting Trellis stack..."
docker compose up -d --build

echo "⏳ Waiting for API to be healthy..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ API is healthy!"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "❌ API failed to start within 30 seconds."
        docker compose logs trellis-api
        exit 1
    fi
    sleep 1
done

echo "⏳ Waiting for Dashboard..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:3000 > /dev/null 2>&1; then
        echo "✅ Dashboard is live!"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "⚠️  Dashboard didn't respond (API demo will still run)."
        break
    fi
    sleep 1
done

echo ""
echo "🎯 Running demo script..."
TRELLIS_API_URL=http://localhost:8000 python examples/demo_multi_agent.py

echo ""
echo "✅ Demo complete!"
echo "   API:       http://localhost:8000"
echo "   Dashboard:  http://localhost:3000"
echo "   Stop with:  docker compose down"
