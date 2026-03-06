#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../lib/setup.sh"

test_start "Homepage loads"

agent-browser open "$BASE_URL/"
agent-browser wait --load networkidle
screenshot "01-homepage-loaded"

# Hero section renders
assert_snapshot_contains "Decision Hub"

# Stats section shows numbers
assert_snapshot_contains "skill"

# Skill cards are visible
assert_element_count_gte "a[href^='/skills/']" 1

test_pass
