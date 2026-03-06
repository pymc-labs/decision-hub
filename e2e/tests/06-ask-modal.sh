#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../lib/setup.sh"

test_start "Ask modal"

agent-browser open "$BASE_URL/"
agent-browser wait --load networkidle

# Open the Ask modal via the nav Ask button (use snapshot to get refs)
agent-browser snapshot -i
agent-browser click "nav button:has-text('Ask')"
agent-browser wait 1000
screenshot "06-ask-modal-open"

# Modal should be visible with a textbox
assert_snapshot_contains "Ask"
assert_element_exists "input[placeholder*='Ask']"

# Type a question
agent-browser fill "input[placeholder*='Ask']" "What skills help with data analysis?"
screenshot "06-ask-modal-typed"

# Submit
agent-browser press Enter
agent-browser wait 3000
screenshot "06-ask-modal-response"

# Close modal
agent-browser press Escape
agent-browser wait 500

test_pass
