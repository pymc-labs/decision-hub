#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../lib/setup.sh"

test_start "Skills listing page"

agent-browser open "$BASE_URL/skills"
agent-browser wait --load networkidle
screenshot "02-skills-listing"

# Page renders
assert_snapshot_contains "Skills"

# Skill cards render
if [[ "$STRICT_MODE" == "true" ]]; then
  assert_element_count_gte "a[href^='/skills/']" 4
else
  assert_element_count_gte "a[href^='/skills/']" 1
fi

# Search input exists
assert_element_exists "input[type='text']"

# Filter controls exist
assert_snapshot_contains "Category"

test_pass
