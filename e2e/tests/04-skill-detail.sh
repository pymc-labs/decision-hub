#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../lib/setup.sh"

test_start "Skill detail page"

if [[ "$STRICT_MODE" == "true" ]]; then
  agent-browser open "$BASE_URL/skills/test-org/data-analyzer"
else
  agent-browser open "$BASE_URL/skills"
  agent-browser wait --load networkidle
  agent-browser click "a[href^='/skills/']"
fi

agent-browser wait --load networkidle
screenshot "04-skill-detail"

# Metadata renders
assert_snapshot_contains "Install"
assert_snapshot_contains "dhub"

# Tabs exist
assert_snapshot_contains "Overview"
assert_snapshot_contains "Evals"
assert_snapshot_contains "Files"

# Click Files tab
agent-browser click "button:has-text('Files')"
agent-browser wait 1000
screenshot "04-skill-detail-files-tab"

# Back to Overview
agent-browser click "button:has-text('Overview')"
agent-browser wait 1000

# Sidebar metadata
assert_snapshot_contains "Category"

if [[ "$STRICT_MODE" == "true" ]]; then
  assert_snapshot_contains "data-analyzer"
  assert_snapshot_contains "test-org"
  assert_snapshot_contains "1.2.0"
fi

test_pass
