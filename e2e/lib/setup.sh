#!/usr/bin/env bash
# e2e/lib/setup.sh — sourced by each test script
set -euo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export REPORT_DIR="${E2E_DIR}/reports"
export BASE_URL="${BASE_URL:-http://localhost:5173}"
export STRICT_MODE="${STRICT_MODE:-true}"

mkdir -p "$REPORT_DIR"

CURRENT_TEST=""
TEST_START_TIME=""

test_start() {
  CURRENT_TEST="$1"
  TEST_START_TIME=$(date +%s)
  echo "--- TEST: $CURRENT_TEST ---"
}

test_pass() {
  local duration=$(( $(date +%s) - TEST_START_TIME ))
  echo "PASS: $CURRENT_TEST (${duration}s)"
  echo "PASS|${CURRENT_TEST}|${duration}" >> "$REPORT_DIR/results.txt"
}

_on_fail() {
  local exit_code=$?
  if [[ $exit_code -ne 0 && -n "$CURRENT_TEST" ]]; then
    local safe_name
    safe_name=$(echo "$CURRENT_TEST" | tr ' /' '_-')
    agent-browser screenshot "$REPORT_DIR/FAIL-${safe_name}.png" 2>/dev/null || true
    local duration=$(( $(date +%s) - TEST_START_TIME ))
    echo "FAIL: $CURRENT_TEST (${duration}s)"
    echo "FAIL|${CURRENT_TEST}|${duration}" >> "$REPORT_DIR/results.txt"
  fi
}
trap _on_fail EXIT

source "${E2E_DIR}/lib/assert.sh"
