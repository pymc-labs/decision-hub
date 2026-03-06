#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../lib/setup.sh"

test_start "Search flow"

agent-browser open "$BASE_URL/skills"
agent-browser wait --load networkidle

# Search for a term
SEARCH_TERM="data"
if [[ "$STRICT_MODE" != "true" ]]; then
  SEARCH_TERM="skill"
fi

agent-browser fill "input[type='text']" "$SEARCH_TERM"

# Wait for debounced results
agent-browser wait 1500
agent-browser wait --load networkidle
screenshot "03-search-results"

# Results should appear
assert_element_count_gte "a[href^='/skills/']" 1

# Click first result and verify navigation
agent-browser click "a[href^='/skills/']"
agent-browser wait --load networkidle
screenshot "03-search-click-result"

assert_url_contains "/skills/"

test_pass
