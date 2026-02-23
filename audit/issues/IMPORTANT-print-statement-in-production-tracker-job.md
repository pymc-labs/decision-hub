# IMPORTANT: Print statement used in production tracker job path

## Category

Important issue (low effort cleanup; deferrable)

## Summary

A production execution path in `modal_app.py` uses `print(...)` instead of structured logger output.

## Evidence

- `server/modal_app.py` includes:
  - `print(f"[check_trackers] Checked {total_checked} tracker(s) in {iterations} iteration(s)", flush=True)`

## Impact

- Inconsistent observability formatting versus the rest of the logging stack.
- Harder log aggregation/filtering for downstream systems expecting structured logger patterns.

## Why this is IMPORTANT (not CRITICAL/BLOCKER)

This does not create a release-breaking functional/security issue, but it is worthwhile hygiene for operational consistency.

## Recommended fix

1. Replace `print(...)` with `logger.info(...)` including the same counters.
2. Keep one consistent logging sink/format for operational telemetry.

