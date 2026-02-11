#!/usr/bin/env bash
# Bump dhub-cli version, publish to PyPI, and optionally sync server.
#
# Usage:
#   ./scripts/release-cli.sh patch             # non-breaking: bump + test + publish
#   ./scripts/release-cli.sh minor             # non-breaking: bump + test + publish
#   ./scripts/release-cli.sh major             # breaking:     bump + test + publish
#   ./scripts/release-cli.sh major --sync      # breaking:     + update MIN_CLI_VERSION + redeploy servers
#
# The --sync flag:
#   - Updates MIN_CLI_VERSION in server/.env.dev and server/.env.prod
#   - Redeploys both dev and prod Modal apps so they reject stale clients
#
# Prerequisites:
#   - uv installed
#   - PyPI API token set via: export UV_PUBLISH_TOKEN=pypi-...
#   - modal CLI configured (only needed with --sync)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/.."
CLIENT_TOML="$ROOT_DIR/client/pyproject.toml"

# Load token from .env if not already set
if [ -z "${UV_PUBLISH_TOKEN:-}" ] && [ -f "$ROOT_DIR/.env" ]; then
    set -a
    source "$ROOT_DIR/.env"
    set +a
fi

# --- Parse args -----------------------------------------------------------

BUMP_LEVEL="${1:-}"
SYNC=false

if [ -z "$BUMP_LEVEL" ]; then
    echo "Usage: $0 <patch|minor|major> [--sync]"
    exit 1
fi

case "$BUMP_LEVEL" in
    patch|minor|major) ;;
    *)
        echo "Error: Invalid bump level '$BUMP_LEVEL'. Must be patch, minor, or major."
        exit 1
        ;;
esac

shift
for arg in "$@"; do
    case $arg in
        --sync) SYNC=true ;;
        *)
            echo "Unknown option: $arg"
            exit 1
            ;;
    esac
done

# --- Read current version --------------------------------------------------

CURRENT_VERSION=$(grep '^version = ' "$CLIENT_TOML" | head -1 | sed 's/version = "\(.*\)"/\1/')
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

case "$BUMP_LEVEL" in
    patch) PATCH=$((PATCH + 1)) ;;
    minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
    major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
esac

NEW_VERSION="$MAJOR.$MINOR.$PATCH"

echo "==> Bumping dhub-cli: $CURRENT_VERSION → $NEW_VERSION ($BUMP_LEVEL)"

# --- Update version in pyproject.toml --------------------------------------

sed -i '' "s/^version = \"$CURRENT_VERSION\"/version = \"$NEW_VERSION\"/" "$CLIENT_TOML"

# --- Run tests -------------------------------------------------------------

echo "==> Running client tests..."
make -C "$ROOT_DIR" test-client

# --- Publish to PyPI -------------------------------------------------------

echo "==> Publishing to PyPI..."
"$SCRIPT_DIR/publish.sh"

# --- Tag the release ---
echo "==> Tagging release: cli/v$NEW_VERSION"
git tag "cli/v$NEW_VERSION"
git push origin "cli/v$NEW_VERSION"

# --- Sync server (only with --sync) ----------------------------------------

if $SYNC; then
    echo ""
    echo "==> Syncing server: updating MIN_CLI_VERSION to $NEW_VERSION"

    for ENV_FILE in "$ROOT_DIR/server/.env.dev" "$ROOT_DIR/server/.env.prod"; do
        sed -i '' "s/^MIN_CLI_VERSION=.*/MIN_CLI_VERSION=$NEW_VERSION/" "$ENV_FILE"
        echo "   Updated $ENV_FILE"
    done

    echo "==> Redeploying dev server..."
    cd "$ROOT_DIR/server" && DHUB_ENV=dev modal deploy modal_app.py

    echo "==> Redeploying prod server..."
    cd "$ROOT_DIR/server" && DHUB_ENV=prod modal deploy modal_app.py

    echo ""
    echo "Done! CLI $NEW_VERSION published and servers redeployed with MIN_CLI_VERSION=$NEW_VERSION"
else
    echo ""
    echo "Done! CLI $NEW_VERSION published to PyPI."
    echo "Servers were NOT redeployed (use --sync for breaking changes)."
fi
