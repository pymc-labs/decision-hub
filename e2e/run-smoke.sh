#!/usr/bin/env bash
# e2e/run-smoke.sh — Run all smoke tests and generate HTML report
set -uo pipefail

E2E_DIR="$(cd "$(dirname "$0")" && pwd)"
REPORT_DIR="${E2E_DIR}/reports"
export REPORT_DIR BASE_URL="${BASE_URL:-http://localhost:5173}" STRICT_MODE="${STRICT_MODE:-true}"

rm -f "$REPORT_DIR/results.txt" "$REPORT_DIR"/*.png "$REPORT_DIR/report.html"
mkdir -p "$REPORT_DIR"

echo "=== E2E Smoke Tests ==="
echo "  URL: $BASE_URL"
echo "  Strict: $STRICT_MODE"
echo ""

TOTAL=0
PASSED=0
FAILED=0

for test_script in "$E2E_DIR"/tests/*.sh; do
  TOTAL=$((TOTAL + 1))
  test_name=$(basename "$test_script" .sh)
  echo "Running: $test_name"

  if bash "$test_script"; then
    PASSED=$((PASSED + 1))
  else
    FAILED=$((FAILED + 1))
  fi
  echo ""

  agent-browser close 2>/dev/null || true
done

echo "=== Results: $PASSED/$TOTAL passed, $FAILED failed ==="

# Generate HTML report
REPORT_FILE="$REPORT_DIR/report.html"
TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M:%S UTC')

cat > "$REPORT_FILE" <<'HTMLEOF'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>E2E Smoke Test Report</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; background: #0a0a0a; color: #e0e0e0; }
  h1 { color: #fff; }
  .meta { color: #888; margin-bottom: 2rem; }
  .summary { display: flex; gap: 2rem; margin-bottom: 2rem; }
  .stat { padding: 1rem; border-radius: 8px; background: #1a1a1a; }
  .stat.pass { border-left: 4px solid #22c55e; }
  .stat.fail { border-left: 4px solid #ef4444; }
  .stat .num { font-size: 2rem; font-weight: bold; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 2rem; }
  th, td { text-align: left; padding: 0.75rem; border-bottom: 1px solid #222; }
  th { color: #888; font-weight: 600; }
  .pass-badge { color: #22c55e; font-weight: 600; }
  .fail-badge { color: #ef4444; font-weight: 600; }
  .screenshots { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1rem; }
  .screenshots img { width: 100%; border-radius: 4px; border: 1px solid #333; }
  .screenshots figure { margin: 0; }
  .screenshots figcaption { font-size: 0.8rem; color: #888; margin-top: 0.25rem; }
</style>
</head>
<body>
HTMLEOF

# Inject dynamic values
cat >> "$REPORT_FILE" <<HTMLEOF
<h1>E2E Smoke Test Report</h1>
<div class="meta">
  <div>Environment: ${BASE_URL}</div>
  <div>Strict mode: ${STRICT_MODE}</div>
  <div>Generated: ${TIMESTAMP}</div>
</div>
<div class="summary">
  <div class="stat pass"><div class="num">${PASSED}</div>passed</div>
  <div class="stat fail"><div class="num">${FAILED}</div>failed</div>
  <div class="stat"><div class="num">${TOTAL}</div>total</div>
</div>
<h2>Results</h2>
<table>
<tr><th>Status</th><th>Test</th><th>Duration</th></tr>
HTMLEOF

if [[ -f "$REPORT_DIR/results.txt" ]]; then
  while IFS='|' read -r status name duration; do
    if [[ "$status" == "PASS" ]]; then
      badge='<span class="pass-badge">PASS</span>'
    else
      badge='<span class="fail-badge">FAIL</span>'
    fi
    echo "<tr><td>${badge}</td><td>${name}</td><td>${duration}s</td></tr>" >> "$REPORT_FILE"
  done < "$REPORT_DIR/results.txt"
fi

cat >> "$REPORT_FILE" <<'HTMLEOF'
</table>
<h2>Screenshots</h2>
<div class="screenshots">
HTMLEOF

for img in "$REPORT_DIR"/*.png; do
  [[ -f "$img" ]] || continue
  fname=$(basename "$img" .png)
  b64=$(base64 -i "$img" 2>/dev/null || base64 "$img" 2>/dev/null)
  cat >> "$REPORT_FILE" <<IMGEOF
<figure>
  <img src="data:image/png;base64,${b64}" alt="${fname}">
  <figcaption>${fname}</figcaption>
</figure>
IMGEOF
done

cat >> "$REPORT_FILE" <<'HTMLEOF'
</div>
</body>
</html>
HTMLEOF

echo "Report: $REPORT_FILE"

[[ $FAILED -eq 0 ]]
