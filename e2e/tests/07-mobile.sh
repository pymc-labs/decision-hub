#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../lib/setup.sh"

test_start "Mobile responsiveness"

# Set mobile viewport
agent-browser resize 400 812

# Homepage
agent-browser open "$BASE_URL/"
agent-browser wait --load networkidle
screenshot "07-mobile-homepage"
assert_snapshot_contains "Decision Hub"

# Skills page
agent-browser open "$BASE_URL/skills"
agent-browser wait --load networkidle
screenshot "07-mobile-skills"
assert_element_count_gte "a[href^='/skills/']" 1

# Skill detail
if [[ "$STRICT_MODE" == "true" ]]; then
  agent-browser open "$BASE_URL/skills/test-org/data-analyzer"
else
  agent-browser click "a[href^='/skills/']"
fi
agent-browser wait --load networkidle
screenshot "07-mobile-detail"
assert_snapshot_contains "Install"

# Reset viewport
agent-browser resize 1280 720

test_pass
