#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../lib/setup.sh"

test_start "Skill detail page"

if [[ "$STRICT_MODE" == "true" ]]; then
  agent-browser open "$BASE_URL/skills/test-org/data-analyzer"
else
  agent-browser open "$BASE_URL/skills"
  agent-browser wait --load networkidle
  agent-browser click "a[href^='/skills/']:first-child"
fi

agent-browser wait --load networkidle
# Wait for detail page content to render (Overview tab only appears on detail page)
assert_element_exists "button:has-text('Overview')"
screenshot "04-skill-detail"

# Metadata renders (install command button shows "dhub install")
assert_snapshot_contains "dhub install"

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

if [[ "$STRICT_MODE" == "true" ]]; then
  # Sidebar metadata (only check in strict mode — dev page layout may differ)
  assert_snapshot_contains "Category"
  assert_snapshot_contains "data-analyzer"
  assert_snapshot_contains "test-org"
  assert_snapshot_contains "1.2.0"
fi

test_pass
