"""Compare gauntlet results at scale against random published skills.

Fetches skills from the dev database, downloads their zip from S3,
runs the gauntlet pipeline in parallel, and compares with the stored grade.

Usage (from server/):
    DHUB_ENV=dev uv run --package decision-hub-server \
        python scripts/gauntlet_comparison.py [--limit 100] [--no-llm] [--workers 8]
"""

import argparse
import csv
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import sqlalchemy as sa

from decision_hub.api.registry_service import run_gauntlet_pipeline
from decision_hub.domain.publish import extract_for_evaluation
from decision_hub.domain.skill_manifest import extract_body, extract_description
from decision_hub.infra.storage import create_s3_client, download_skill_zip
from decision_hub.settings import create_settings


def fetch_random_skills(engine, limit: int) -> list[dict]:
    """Fetch N random published skills with their S3 keys."""
    query = sa.text("""
        SELECT
            o.slug AS org_slug,
            s.name AS skill_name,
            s.latest_semver AS version,
            v.eval_status AS stored_grade,
            v.s3_key,
            v.id AS version_id,
            s.category
        FROM skills s
        JOIN organizations o ON s.org_id = o.id
        JOIN versions v ON v.skill_id = s.id AND v.semver = s.latest_semver
        WHERE s.latest_semver IS NOT NULL
          AND v.s3_key IS NOT NULL
        ORDER BY RANDOM()
        LIMIT :limit
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, {"limit": limit}).mappings().all()
    return [dict(r) for r in rows]


def fetch_same_skills(engine, fqns: list[str]) -> list[dict]:
    """Fetch specific skills by org_slug/skill_name pairs."""
    # Build WHERE clause for each fqn
    conditions = []
    params = {}
    for i, fqn in enumerate(fqns):
        org, name = fqn.split("/", 1)
        conditions.append(f"(o.slug = :org_{i} AND s.name = :name_{i})")
        params[f"org_{i}"] = org
        params[f"name_{i}"] = name

    where = " OR ".join(conditions)
    query = sa.text(f"""
        SELECT
            o.slug AS org_slug,
            s.name AS skill_name,
            s.latest_semver AS version,
            v.eval_status AS stored_grade,
            v.s3_key,
            v.id AS version_id,
            s.category
        FROM skills s
        JOIN organizations o ON s.org_id = o.id
        JOIN versions v ON v.skill_id = s.id AND v.semver = s.latest_semver
        WHERE s.latest_semver IS NOT NULL
          AND v.s3_key IS NOT NULL
          AND ({where})
    """)
    with engine.connect() as conn:
        rows = conn.execute(query, params).mappings().all()
    return [dict(r) for r in rows]


def run_gauntlet_for_skill(
    s3_client,
    bucket: str,
    skill: dict,
    settings,
    use_llm: bool,
) -> dict:
    """Download a skill zip, run the gauntlet, and return comparison data."""
    org_slug = skill["org_slug"]
    skill_name = skill["skill_name"]
    fqn = f"{org_slug}/{skill_name}"

    result = {
        "fqn": fqn,
        "version": skill["version"],
        "stored_grade": skill["stored_grade"],
        "new_grade": None,
        "grade_changed": False,
        "checks_failed": [],
        "checks_warned": [],
        "duration_ms": 0,
        "error": None,
        "num_source_files": 0,
        "total_source_kb": 0,
        "llm_used": use_llm,
    }

    try:
        # Download zip from S3
        zip_bytes = download_skill_zip(s3_client, bucket, skill["s3_key"])

        # Extract contents
        skill_md_content, source_files, lockfile_content, unscanned_files = extract_for_evaluation(zip_bytes)

        description = extract_description(skill_md_content)
        skill_md_body = extract_body(skill_md_content)

        # Parse allowed_tools from manifest
        allowed_tools = None
        try:
            import tempfile

            from decision_hub.domain.skill_manifest import parse_skill_md

            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as tmp:
                tmp.write(skill_md_content)
                tmp_path = Path(tmp.name)
            manifest = parse_skill_md(tmp_path)
            allowed_tools = manifest.allowed_tools
            tmp_path.unlink()
        except (ValueError, KeyError, OSError):
            pass

        result["num_source_files"] = len(source_files)
        result["total_source_kb"] = round(sum(len(c) for _, c in source_files) / 1024, 1)

        # Run gauntlet with timing
        t0 = time.monotonic()
        report, _check_results_dicts, _llm_reasoning = run_gauntlet_pipeline(
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
        result["grade_changed"] = report.grade != skill["stored_grade"]
        result["duration_ms"] = elapsed_ms
        result["checks_failed"] = [f"{r.check_name}: {r.message}" for r in report.results if r.severity == "fail"]
        result["checks_warned"] = [f"{r.check_name}: {r.message}" for r in report.results if r.severity == "warn"]
        result["gauntlet_summary"] = report.gauntlet_summary or report.summary

    except (ValueError, KeyError, RuntimeError, OSError, httpx.HTTPError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


def print_summary(results: list[dict]) -> None:
    """Print a summary of gauntlet comparison results."""
    total = len(results)
    errors = [r for r in results if r["error"]]
    ok = total - len(errors)

    grade_order = {"A": 0, "B": 1, "C": 2, "F": 3}
    grade_changes = {"upgrade": [], "downgrade": [], "same": []}
    durations = []

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
    print("GAUNTLET COMPARISON SUMMARY")
    print("=" * 70)
    print(f"Total skills tested: {total}")
    print(f"Successfully analyzed: {ok}")
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


def main():
    parser = argparse.ArgumentParser(description="Gauntlet comparison at scale")
    parser.add_argument("--limit", type=int, default=100, help="Number of skills to test")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM calls (regex-only)")
    parser.add_argument("--output", default="gauntlet_comparison.csv", help="Output CSV path")
    parser.add_argument("--workers", type=int, default=8, help="Number of parallel workers")
    parser.add_argument("--same-skills", type=str, default="", help="Path to previous CSV to reuse the same skill set")
    args = parser.parse_args()

    settings = create_settings()
    engine = sa.create_engine(settings.database_url, connect_args={"options": "-c statement_timeout=30000"})

    s3_client = create_s3_client(
        region=settings.aws_region,
        access_key_id=settings.aws_access_key_id,
        secret_access_key=settings.aws_secret_access_key,
        endpoint_url=settings.s3_endpoint_url,
    )

    use_llm = not args.no_llm and bool(settings.google_api_key)
    if args.no_llm:
        print("Running in regex-only mode (no LLM)")
        settings = settings.model_copy(update={"google_api_key": ""})
    elif not settings.google_api_key:
        print("WARNING: No GOOGLE_API_KEY configured — falling back to regex-only")
        use_llm = False
    else:
        print("Running with LLM judge enabled")

    # Fetch skills — either same set from previous CSV or random
    if args.same_skills:
        print(f"\nLoading skill list from {args.same_skills}...")
        with open(args.same_skills) as f:
            prev_rows = list(csv.DictReader(f))
        fqns = [r["fqn"] for r in prev_rows]
        skills = fetch_same_skills(engine, fqns)
        print(f"Matched {len(skills)}/{len(fqns)} skills from previous run")
    else:
        print(f"\nFetching {args.limit} random published skills from dev...")
        skills = fetch_random_skills(engine, args.limit)
    print(f"Got {len(skills)} skills\n")

    if not skills:
        print("No skills found!")
        sys.exit(1)

    # Run gauntlet in parallel
    results = []
    completed = 0
    total = len(skills)
    t_start = time.monotonic()

    print(f"Running gauntlet with {args.workers} workers...\n")

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_skill = {
            executor.submit(run_gauntlet_for_skill, s3_client, settings.s3_bucket, skill, settings, use_llm): skill
            for skill in skills
        }

        for future in as_completed(future_to_skill):
            completed += 1
            result = future.result()
            results.append(result)

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
            print(f"[{completed:3d}/{total}] {fqn:60s} {status}  (ETA {eta:.0f}s)", flush=True)

    # Write CSV
    csv_path = Path(args.output)
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
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
                "gauntlet_summary",
                "error",
                "llm_used",
            ],
        )
        writer.writeheader()
        for r in sorted(results, key=lambda x: x["fqn"]):
            row = dict(r)
            row["checks_failed"] = "; ".join(row.get("checks_failed", []))
            row["checks_warned"] = "; ".join(row.get("checks_warned", []))
            writer.writerow(row)

    wall_time = time.monotonic() - t_start
    print(f"\nResults written to {csv_path}")
    print(f"Wall time: {wall_time:.0f}s ({wall_time / 60:.1f}min)")

    print_summary(results)


if __name__ == "__main__":
    main()
