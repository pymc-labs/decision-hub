"""Re-grade all published skills through the current gauntlet pipeline.

Fetches every latest-version skill from the DB, downloads each zip from S3,
re-runs the gauntlet pipeline, and updates the stored grade + summary.

Usage (from server/):
    DHUB_ENV=dev uv run --package decision-hub-server \
        python scripts/backfill_gauntlet.py [--dry-run] [--limit 50] [--workers 8]
"""

import argparse
import csv
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from uuid import UUID

import sqlalchemy as sa

from decision_hub.api.registry_service import run_gauntlet_pipeline
from decision_hub.domain.publish import extract_for_evaluation
from decision_hub.domain.skill_manifest import (
    extract_body,
    extract_description,
    parse_skill_md,
)
from decision_hub.infra.database import (
    _refresh_skill_latest_version,
    create_engine,
    eval_audit_logs_table,
    insert_audit_log,
    versions_table,
)
from decision_hub.infra.storage import create_s3_client, download_skill_zip
from decision_hub.settings import create_settings, get_env

# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------


def fetch_all_latest_versions(engine: sa.Engine, limit: int | None) -> list[dict]:
    """Fetch every published skill's latest version, ordered deterministically."""
    query = sa.text("""
        SELECT
            o.slug        AS org_slug,
            s.name        AS skill_name,
            s.id          AS skill_id,
            v.id          AS version_id,
            v.semver      AS version,
            v.s3_key,
            v.eval_status AS stored_grade,
            v.gauntlet_summary AS stored_summary
        FROM skills s
        JOIN organizations o ON s.org_id = o.id
        JOIN versions v ON v.skill_id = s.id AND v.semver = s.latest_semver
        WHERE s.latest_semver IS NOT NULL
          AND v.s3_key IS NOT NULL
        ORDER BY o.slug, s.name
        LIMIT :limit
    """)
    params = {"limit": limit if limit else 2_000_000}
    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Per-skill grading (pure, no DB writes)
# ---------------------------------------------------------------------------


def regrade_skill(
    s3_client,
    bucket: str,
    skill: dict,
    settings,
) -> dict:
    """Download zip, run gauntlet pipeline, return result dict."""
    org_slug = skill["org_slug"]
    skill_name = skill["skill_name"]
    fqn = f"{org_slug}/{skill_name}"

    result = {
        "fqn": fqn,
        "skill_id": skill["skill_id"],
        "version_id": skill["version_id"],
        "version": skill["version"],
        "stored_grade": skill["stored_grade"],
        "stored_summary": skill["stored_summary"],
        "new_grade": None,
        "new_summary": None,
        "grade_changed": False,
        "duration_ms": 0,
        "num_source_files": 0,
        "total_source_kb": 0,
        "checks_failed": [],
        "checks_warned": [],
        "error": None,
    }

    try:
        zip_bytes = download_skill_zip(s3_client, bucket, skill["s3_key"])
        skill_md_content, source_files, lockfile_content, unscanned_files = extract_for_evaluation(zip_bytes)

        description = extract_description(skill_md_content)
        skill_md_body = extract_body(skill_md_content)

        # Parse allowed_tools from manifest
        allowed_tools = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp:
                tmp.write(skill_md_content)
                tmp_path = Path(tmp.name)
            manifest = parse_skill_md(tmp_path)
            allowed_tools = manifest.allowed_tools
            tmp_path.unlink()
        except Exception:
            pass

        result["num_source_files"] = len(source_files)
        result["total_source_kb"] = round(sum(len(c) for _, c in source_files) / 1024, 1)

        t0 = time.monotonic()
        report, check_dicts, llm_reasoning = run_gauntlet_pipeline(
            skill_md_content,
            lockfile_content,
            source_files,
            skill_name=skill_name,
            description=description,
            skill_md_body=skill_md_body,
            settings=settings,
            allowed_tools=allowed_tools,
            llm_required=False,
            unscanned_files=unscanned_files,
        )
        elapsed_ms = round((time.monotonic() - t0) * 1000)

        result["new_grade"] = report.grade
        result["new_summary"] = report.gauntlet_summary or report.summary
        result["grade_changed"] = report.grade != skill["stored_grade"]
        result["duration_ms"] = elapsed_ms
        result["check_results_dicts"] = check_dicts
        result["llm_reasoning"] = llm_reasoning
        result["checks_failed"] = [f"{r.check_name}: {r.message}" for r in report.results if r.severity == "fail"]
        result["checks_warned"] = [f"{r.check_name}: {r.message}" for r in report.results if r.severity == "warn"]
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


# ---------------------------------------------------------------------------
# DB write: batch flush
# ---------------------------------------------------------------------------


def flush_updates(engine: sa.Engine, results: list[dict]) -> int:
    """Write new grades + summaries, replace audit logs, and refresh skills.

    For each skill: updates the version row, deletes all old audit log
    entries for that version, inserts a fresh audit log with the new
    check results, and refreshes the denormalized skills columns.

    Returns the number of rows updated.
    """
    updatable = [r for r in results if r["new_grade"] and not r["error"]]
    if not updatable:
        return 0

    with engine.begin() as conn:
        for r in updatable:
            version_id = UUID(str(r["version_id"]))
            org_slug, skill_name = r["fqn"].split("/", 1)

            conn.execute(
                versions_table.update()
                .where(versions_table.c.id == version_id)
                .values(
                    eval_status=r["new_grade"],
                    gauntlet_summary=r["new_summary"],
                )
            )

            # Delete ALL old audit logs for this skill (old logs may have
            # version_id=NULL which wouldn't match a UUID comparison)
            conn.execute(
                eval_audit_logs_table.delete().where(
                    sa.and_(
                        eval_audit_logs_table.c.org_slug == org_slug,
                        eval_audit_logs_table.c.skill_name == skill_name,
                    )
                )
            )
            insert_audit_log(
                conn,
                org_slug=org_slug,
                skill_name=skill_name,
                semver=r["version"],
                grade=r["new_grade"],
                check_results=r.get("check_results_dicts", []),
                publisher="backfill",
                version_id=version_id,
                llm_reasoning=r.get("llm_reasoning"),
            )

            _refresh_skill_latest_version(conn, UUID(str(r["skill_id"])))

    return len(updatable)


# ---------------------------------------------------------------------------
# Summary (reuse the comparison script's format)
# ---------------------------------------------------------------------------


def print_summary(results: list[dict]) -> None:
    """Print a summary of gauntlet backfill results."""
    total = len(results)
    errors = [r for r in results if r["error"]]
    ok = total - len(errors)

    grade_order = {"A": 0, "B": 1, "C": 2, "F": 3}
    grade_changes: dict[str, list[dict]] = {
        "upgrade": [],
        "downgrade": [],
        "same": [],
    }
    durations: list[int] = []

    for r in results:
        if r["error"]:
            continue
        durations.append(r["duration_ms"])
        if r["grade_changed"]:
            old_rank = grade_order.get(r["stored_grade"], 99)
            new_rank = grade_order.get(r["new_grade"], 99)
            if new_rank > old_rank:
                grade_changes["downgrade"].append(r)
            else:
                grade_changes["upgrade"].append(r)
        else:
            grade_changes["same"].append(r)

    print("\n" + "=" * 70)
    print("GAUNTLET BACKFILL SUMMARY")
    print("=" * 70)
    print(f"Total skills processed: {total}")
    print(f"Successfully graded: {ok}")
    print(f"Errors: {len(errors)}")
    print()

    if durations:
        durations.sort()
        avg_ms = sum(durations) / len(durations)
        p50 = durations[len(durations) // 2]
        p95 = durations[int(len(durations) * 0.95)]
        print(f"Timing (ms): avg={avg_ms:.0f}  p50={p50}  p95={p95}  min={min(durations)}  max={max(durations)}")
        print()

    if ok:
        print(f"Grade unchanged: {len(grade_changes['same'])} ({len(grade_changes['same']) * 100 / ok:.1f}%)")
    print(f"Upgrades (grade improved): {len(grade_changes['upgrade'])}")
    print(f"Downgrades (grade got worse): {len(grade_changes['downgrade'])}")

    print("\nGrade distribution:")
    for grade in ["A", "B", "C", "F"]:
        old_count = sum(1 for r in results if r["stored_grade"] == grade and not r["error"])
        new_count = sum(1 for r in results if r["new_grade"] == grade)
        print(f"  {grade}: {old_count} (stored) -> {new_count} (new)")

    print("\nTransition matrix:")
    for old_g in ["A", "B", "C", "F"]:
        for new_g in ["A", "B", "C", "F"]:
            count = sum(1 for r in results if not r["error"] and r["stored_grade"] == old_g and r["new_grade"] == new_g)
            if count > 0:
                print(f"  {old_g} -> {new_g}: {count}")

    if grade_changes["downgrade"]:
        print("\n" + "-" * 70)
        print("DOWNGRADES:")
        print("-" * 70)
        for r in grade_changes["downgrade"]:
            print(f"\n  {r['fqn']} v{r['version']}")
            print(f"    {r['stored_grade']} -> {r['new_grade']}")
            print(f"    Files: {r['num_source_files']}, Size: {r['total_source_kb']}KB")
            if r["checks_failed"]:
                print(f"    Failed: {'; '.join(r['checks_failed'][:3])}")
                if len(r["checks_failed"]) > 3:
                    print(f"    ... and {len(r['checks_failed']) - 3} more")
            if r["checks_warned"]:
                print(f"    Warned: {'; '.join(r['checks_warned'][:3])}")

    if grade_changes["upgrade"]:
        print("\n" + "-" * 70)
        print("UPGRADES:")
        print("-" * 70)
        for r in grade_changes["upgrade"]:
            print(f"  {r['fqn']} v{r['version']}: {r['stored_grade']} -> {r['new_grade']}")

    if errors:
        print("\n" + "-" * 70)
        print("ERRORS:")
        print("-" * 70)
        for r in errors:
            print(f"  {r['fqn']}: {r['error']}")

    print()


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

CSV_FIELDS = [
    "fqn",
    "version",
    "stored_grade",
    "new_grade",
    "grade_changed",
    "duration_ms",
    "num_source_files",
    "total_source_kb",
    "checks_failed",
    "checks_warned",
    "new_summary",
    "error",
]


def write_csv(results: list[dict], path: Path) -> None:
    """Write results to CSV for audit trail."""
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in sorted(results, key=lambda x: x["fqn"]):
            row = dict(r)
            row["checks_failed"] = "; ".join(row.get("checks_failed", []))
            row["checks_warned"] = "; ".join(row.get("checks_warned", []))
            writer.writerow(row)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-grade all published skills through the current gauntlet pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run pipeline but skip DB writes; print comparison summary only",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N skills (for testing)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of parallel workers (default: 8)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of results to flush to DB per batch (default: 50)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output CSV path for audit trail (default: gauntlet_backfill_{env}.csv)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip skills whose grade already matches the new pipeline output",
    )
    args = parser.parse_args()

    env = get_env()
    settings = create_settings()
    engine = create_engine(settings.database_url)

    s3_client = create_s3_client(
        region=settings.aws_region,
        access_key_id=settings.aws_access_key_id,
        secret_access_key=settings.aws_secret_access_key,
        endpoint_url=settings.s3_endpoint_url,
    )

    # LLM availability
    if not settings.google_api_key:
        print("WARNING: No GOOGLE_API_KEY — falling back to regex-only grading")
    else:
        print("Running with LLM judge enabled")

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    print(f"\nEnvironment: {env}  |  Mode: {mode}  |  Workers: {args.workers}")
    if args.limit:
        print(f"Limit: {args.limit} skills")

    # Fetch skills
    print("\nFetching latest versions from DB...")
    skills = fetch_all_latest_versions(engine, args.limit)
    print(f"Found {len(skills)} skills to process")

    if not skills:
        print("No skills found!")
        sys.exit(1)

    # Resume: filter out skills that don't need re-grading
    if args.resume:
        original_count = len(skills)
        # Skip skills already processed by a previous (interrupted) run.
        # Grade-A skills have gauntlet_summary=None by design (no findings),
        # so we treat any valid grade as "done" for A, and require a non-null
        # summary for B/C/F (which always produce one).
        _VALID_GRADES = {"A", "B", "C", "F"}
        skills = [
            s
            for s in skills
            if s["stored_grade"] not in _VALID_GRADES or (s["stored_grade"] != "A" and not s["stored_summary"])
        ]
        skipped = original_count - len(skills)
        if skipped:
            print(f"Resume: skipping {skipped} already-graded skills")
            print(f"Remaining: {len(skills)} skills")

    if not skills:
        print("All skills already graded — nothing to do.")
        sys.exit(0)

    # Parallel grading with interleaved DB flushes
    results: list[dict] = []
    pending_flush: list[dict] = []
    completed = 0
    total_updated = 0
    batch_num = 0
    total = len(skills)
    t_start = time.monotonic()

    print(f"\nGrading {total} skills with {args.workers} workers...\n")

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_skill = {
            executor.submit(regrade_skill, s3_client, settings.s3_bucket, skill, settings): skill for skill in skills
        }

        for future in as_completed(future_to_skill):
            completed += 1
            result = future.result()
            results.append(result)

            # Accumulate successful results for DB flush
            if not args.dry_run and result["new_grade"] and not result["error"]:
                pending_flush.append(result)

            fqn = result["fqn"]
            if result["error"]:
                status = f"ERROR: {result['error'][:80]}"
            elif result["grade_changed"]:
                status = f"{result['stored_grade']} -> {result['new_grade']}  ({result['duration_ms']}ms)"
            else:
                status = f"{result['new_grade']}  ({result['duration_ms']}ms)"

            elapsed = time.monotonic() - t_start
            rate = completed / elapsed if elapsed > 0 else 0
            eta = (total - completed) / rate if rate > 0 else 0
            print(
                f"[{completed:3d}/{total}] {fqn:60s} {status}  (ETA {eta:.0f}s)",
                flush=True,
            )

            # Flush to DB when batch is full
            if len(pending_flush) >= args.batch_size:
                batch_num += 1
                n = flush_updates(engine, pending_flush)
                total_updated += n
                print(f"  >> Flushed batch {batch_num} ({n} rows, {total_updated} total)")
                pending_flush.clear()

    # Flush remaining results
    if args.dry_run:
        print("\n[DRY-RUN] Skipped DB writes")
    elif pending_flush:
        batch_num += 1
        n = flush_updates(engine, pending_flush)
        total_updated += n
        print(f"  >> Flushed batch {batch_num} ({n} rows, {total_updated} total)")

    if total_updated:
        print(f"\nUpdated {total_updated} versions in DB")

    # CSV output
    csv_path = Path(args.output) if args.output else Path(f"gauntlet_backfill_{env}.csv")
    write_csv(results, csv_path)

    wall_time = time.monotonic() - t_start
    print(f"\nResults written to {csv_path}")
    print(f"Wall time: {wall_time:.0f}s ({wall_time / 60:.1f}min)")

    print_summary(results)


if __name__ == "__main__":
    main()
