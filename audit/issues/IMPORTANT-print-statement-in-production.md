# IMPORTANT: print() Statement in Production Code

## Summary

A `print()` statement is used instead of the project's standard `loguru`
logger in the tracker cron function.

## Affected Files

- `server/modal_app.py:387`

```python
print(f"[check_trackers] Checked {total_checked} tracker(s) in {iterations} iteration(s)", flush=True)
```

## Context

The rest of the codebase consistently uses `from loguru import logger` for
all logging. This single `print()` bypasses the logging configuration
(log level, formatting, request ID correlation).

## Recommended Fix

Replace with:

```python
logger.info("check_trackers completed total_checked={} iterations={}", total_checked, iterations)
```

## Deferral Rationale

Minor code quality issue. Does not affect functionality or security.
