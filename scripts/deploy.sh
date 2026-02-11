#!/usr/bin/env bash
# Deploy Decision Hub (API + frontend) to Modal.
#
# Usage:
#   DHUB_ENV=dev  ./scripts/deploy.sh     # deploy to dev
#   DHUB_ENV=prod ./scripts/deploy.sh     # deploy to prod
#
# Steps:
#   1. Build the React frontend (npm run build)
#   2. Apply database migrations
#   3. Deploy the Modal app (which bakes in frontend/dist/)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DHUB_ENV="${DHUB_ENV:-dev}"

echo "=== Decision Hub deploy (env=$DHUB_ENV) ==="

# --- 1. Build frontend ---
echo ""
echo ">>> Building frontend..."
cd "$REPO_ROOT/frontend"

# Install deps if node_modules is missing
if [ ! -d node_modules ]; then
  echo "    Installing npm dependencies..."
  npm ci --silent
fi

# Set the API base to empty string so the SPA uses relative URLs
VITE_API_URL="" npx vite build

echo "    Frontend built: $(du -sh dist | cut -f1)"

# --- 2. Apply database migrations ---
echo ""
echo ">>> Applying database migrations (env=$DHUB_ENV)..."
cd "$REPO_ROOT/server"

DHUB_ENV="$DHUB_ENV" uv run --package decision-hub-server python ../scripts/run_migrations.py

# --- 3. Deploy Modal app ---
echo ""
echo ">>> Deploying Modal app (env=$DHUB_ENV)..."

DHUB_ENV="$DHUB_ENV" modal deploy modal_app.py

echo ""
echo "=== Deploy complete ==="
if [ "$DHUB_ENV" = "prod" ]; then
  echo "    URL: https://lfiaschi--api.modal.run"
else
  echo "    URL: https://lfiaschi--api-$DHUB_ENV.modal.run"
fi

# --- 4. Tag prod deploys for tracking ---
if [ "$DHUB_ENV" = "prod" ]; then
  TAG="prod/$(date -u +%Y%m%d-%H%M%S)"
  echo ""
  echo ">>> Tagging deploy: $TAG"
  git tag "$TAG"
  git push origin "$TAG"
fi
