#!/usr/bin/env bash
# Publish the dhub client package to PyPI.
#
# Prerequisites:
#   - uv installed (https://docs.astral.sh/uv/)
#   - PyPI API token set via: export UV_PUBLISH_TOKEN=pypi-...
#     Or use: --token flag
#
# Usage:
#   ./scripts/publish.sh              # build + publish to PyPI
#   ./scripts/publish.sh --test       # build + publish to TestPyPI first
#   ./scripts/publish.sh --build-only # build without publishing
#
# After publishing, install with:
#   uv tool install dhub-cli

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/.."
DIST_DIR="$ROOT_DIR/dist"

# Load token from .env if not already set
if [ -z "${UV_PUBLISH_TOKEN:-}" ] && [ -f "$ROOT_DIR/.env" ]; then
    set -a
    source "$ROOT_DIR/.env"
    set +a
fi

BUILD_ONLY=false
USE_TEST_PYPI=false

for arg in "$@"; do
    case $arg in
        --build-only) BUILD_ONLY=true ;;
        --test)       USE_TEST_PYPI=true ;;
        --help|-h)
            head -15 "$0" | tail -13 | sed 's/^# \?//'
            exit 0
            ;;
        *)
            echo "Unknown option: $arg"
            exit 1
            ;;
    esac
done

echo "==> Cleaning previous builds..."
rm -rf "$DIST_DIR"

# --- Publish dhub-core first (dhub-cli depends on it) ---

echo "==> Building dhub-core..."
uv build --package dhub-core --directory "$ROOT_DIR"

if ! $BUILD_ONLY; then
    if $USE_TEST_PYPI; then
        echo "==> Publishing dhub-core to TestPyPI..."
        uv publish --publish-url https://test.pypi.org/legacy/ "$DIST_DIR"/* || true
    else
        echo "==> Publishing dhub-core to PyPI..."
        uv publish "$DIST_DIR"/* || true
    fi
fi

rm -rf "$DIST_DIR"

# --- Build and publish dhub-cli ---

echo "==> Building dhub-cli..."
uv build --package dhub-cli --directory "$ROOT_DIR"

echo ""
echo "==> Built artifacts:"
ls -lh "$DIST_DIR"

if $BUILD_ONLY; then
    echo ""
    echo "Done (build only). Artifacts in $DIST_DIR"
    exit 0
fi

if $USE_TEST_PYPI; then
    echo ""
    echo "==> Publishing dhub-cli to TestPyPI..."
    uv publish --publish-url https://test.pypi.org/legacy/ "$DIST_DIR"/*
    echo ""
    echo "Published to TestPyPI. Install with:"
    echo "  uv tool install dhub-cli --index-url https://test.pypi.org/simple/"
else
    echo ""
    echo "==> Publishing dhub-cli to PyPI..."
    uv publish "$DIST_DIR"/*
    echo ""
    echo "Published to PyPI. Install with:"
    echo "  uv tool install dhub-cli"
fi
