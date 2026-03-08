"""Admin script to inspect tracker health.

Prints a summary table to stdout showing total/enabled/disabled counts,
due-now trackers, recent activity, the most common errors, and recent
cron-tick metrics from the tracker_metrics table.

Usage:
    cd server && DHUB_ENV=dev uv run --package decision-hub-server \
        python -m decision_hub.scripts.tracker_health
"""

import sys
from collections import Counter
from datetime import UTC, datetime

import sqlalchemy as sa

from decision_hub.infra.database import create_engine, list_tracker_metrics, skill_trackers_table
from decision_hub.settings import create_settings


def _run() -> None:
    settings = create_settings()
    engine = create_engine(settings.database_url)

    with engine.connect() as conn:
        rows = conn.execute(sa.select(skill_trackers_table)).all()

    if not rows:
        print("No trackers found.")
    else:
        _print_tracker_summary(rows)

    _print_cron_metrics(engine)


def _print_tracker_summary(rows: list) -> None:
    """Print the tracker health summary section."""
    now = datetime.now(UTC)
    total = len(rows)
    enabled = sum(1 for r in rows if r.enabled)
    disabled = total - enabled
    due_now = sum(1 for r in rows if r.enabled and (r.next_check_at is None or r.next_check_at <= now))
    checked_last_hour = sum(1 for r in rows if r.last_checked_at and (now - r.last_checked_at).total_seconds() < 3600)
    with_error = [r for r in rows if r.last_error and r.enabled]
    last_checked_at = max(
        (r.last_checked_at for r in rows if r.last_checked_at),
        default=None,
    )

    print("=== Tracker Health Summary ===")
    print(f"  Total:            {total}")
    print(f"  Enabled:          {enabled}")
    print(f"  Disabled:         {disabled}")
    print(f"  Due now:          {due_now}")
    print(f"  Checked last hr:  {checked_last_hour}")
    print(f"  Failed (enabled): {len(with_error)}")
    if last_checked_at:
        age = (now - last_checked_at).total_seconds()
        print(f"  Last run:         {last_checked_at.isoformat()} ({int(age)}s ago)")
    else:
        print("  Last run:         never")

    if with_error:
        # Group errors by first 60 chars of message for dedup
        error_counter: Counter[str] = Counter()
        for r in with_error:
            prefix = (r.last_error or "")[:60]
            error_counter[prefix] += 1

        print("\n--- Top Errors ---")
        for msg, count in error_counter.most_common(5):
            print(f"  [{count}x] {msg}")

    print()


def _print_cron_metrics(engine: sa.engine.Engine) -> None:
    """Print recent cron-tick metrics from the tracker_metrics table."""
    with engine.connect() as conn:
        metrics = list_tracker_metrics(conn, limit=24)

    if not metrics:
        print("=== Recent Cron Ticks ===")
        print("  No metrics recorded yet.")
        print()
        return

    print("=== Recent Cron Ticks ===")
    for m in metrics:
        ts = m.recorded_at.strftime("%Y-%m-%d %H:%M:%S")
        rate_str = str(m.github_rate_remaining) if m.github_rate_remaining is not None else "n/a"
        print(
            f"  {ts}  checked={m.total_checked}  changed={m.trackers_changed}"
            f"  failed={m.trackers_failed}  disabled={m.trackers_disabled}"
            f"  rate={rate_str}  dur={m.batch_duration_seconds:.1f}s"
        )
    print()


if __name__ == "__main__":
    _run()
    sys.exit(0)
