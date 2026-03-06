#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../lib/setup.sh"

test_start "Skill spotlight checks"

if [[ "$STRICT_MODE" != "true" ]]; then
  echo "SKIP: spotlight checks require STRICT_MODE (local env with seed data)"
  test_pass
  exit 0
fi

# org/name|expected_description|expected_version|expected_category
SKILLS=(
  "test-org/data-analyzer|Analyze datasets|1.2.0|Data Science"
  "test-org/code-reviewer|Automated code review|0.5.0|Coding"
  "acme-corp/deploy-helper|Streamline deployments|2.0.1|DevOps"
)

for entry in "${SKILLS[@]}"; do
  IFS='|' read -r path desc version category <<< "$entry"
  echo "  Checking: $path"

  agent-browser open "$BASE_URL/skills/$path"
  agent-browser wait --load networkidle

  safe_name=$(echo "$path" | tr '/' '-')
  screenshot "05-spotlight-${safe_name}"

  # Content correctness
  assert_snapshot_contains "$desc"

  # Data integrity
  assert_snapshot_contains "$version"

  # Structural completeness
  assert_snapshot_contains "$category"

  # Interactive: tabs exist
  agent-browser click "button:has-text('Overview')"
  agent-browser wait 500

  # Install command block
  assert_snapshot_contains "dhub install"
done

test_pass
