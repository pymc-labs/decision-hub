#!/usr/bin/env bash
# e2e/lib/assert.sh — assertion helpers built on agent-browser primitives

assert_element_exists() {
  local selector="$1"
  local timeout="${2:-10000}"
  if ! agent-browser wait "$selector" --timeout "$timeout" 2>/dev/null; then
    echo "ASSERT FAILED: element '$selector' not found within ${timeout}ms"
    return 1
  fi
}

assert_element_text() {
  local selector="$1"
  local expected="$2"
  local actual
  actual=$(agent-browser get text "$selector" 2>/dev/null)
  if ! echo "$actual" | grep -qi "$expected"; then
    echo "ASSERT FAILED: text of '$selector' does not contain '$expected'"
    echo "  Actual: $actual"
    return 1
  fi
}

assert_snapshot_contains() {
  local expected="$1"
  local snap
  # Use full snapshot (not -i) to include static text, labels, and descriptions
  snap=$(agent-browser snapshot 2>/dev/null)
  if ! echo "$snap" | grep -qi "$expected"; then
    echo "ASSERT FAILED: snapshot does not contain '$expected'"
    return 1
  fi
}

assert_url_contains() {
  local expected="$1"
  local actual
  actual=$(agent-browser get url 2>/dev/null)
  if ! echo "$actual" | grep -q "$expected"; then
    echo "ASSERT FAILED: URL does not contain '$expected'"
    echo "  Actual: $actual"
    return 1
  fi
}

assert_element_count_gte() {
  local selector="$1"
  local min_count="$2"
  local count
  count=$(agent-browser eval --stdin <<EVALEOF
document.querySelectorAll("${selector}").length
EVALEOF
  )
  count=$(echo "$count" | tr -dc '0-9')
  if [[ -z "$count" || "$count" -lt "$min_count" ]]; then
    echo "ASSERT FAILED: expected >= $min_count elements for '$selector', found ${count:-empty}"
    return 1
  fi
}

screenshot() {
  local name="$1"
  agent-browser screenshot "$REPORT_DIR/${name}.png" 2>/dev/null
}
