"""Compare skill classification between Gemini and OpenRouter (Qwen).

Runs the exact ``classify_skill`` prompt against both backends for a
sample of published skills and reports agreement, so the impact of
switching the default gauntlet/classification provider can be
quantified before flipping prod.

Usage (from server/):
    DHUB_ENV=dev uv run --package decision-hub-server \
        python -m decision_hub.scripts.compare_classification --limit 100

Results are appended to a JSONL file incrementally; re-running with
``--resume`` (default) skips already-compared skills.
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import sqlalchemy as sa
from loguru import logger

from decision_hub.domain.classification import build_taxonomy_prompt_fragment, parse_classification_response
from decision_hub.domain.publish import extract_for_evaluation
from decision_hub.domain.skill_manifest import extract_body
from decision_hub.infra.database import create_engine, organizations_table, skills_table, versions_table
from decision_hub.infra.gemini import classify_skill, create_gemini_client
from decision_hub.infra.openrouter import create_openrouter_client
from decision_hub.infra.storage import create_s3_client, download_skill_zip
from decision_hub.settings import Settings, create_settings


def _fetch_sample(settings: Settings, limit: int) -> list[dict]:
    """Fetch a deterministic sample of public skills with their latest version s3_key.

    Fetches the skill sample first, then the latest version per skill via
    indexed point lookups — a single group-by over the whole versions
    table exceeds the 30s statement timeout.
    """
    engine = create_engine(settings.database_url)
    skills_stmt = (
        sa.select(
            skills_table.c.id,
            skills_table.c.name,
            skills_table.c.description,
            skills_table.c.category,
            organizations_table.c.slug.label("org_slug"),
        )
        .select_from(skills_table.join(organizations_table, skills_table.c.org_id == organizations_table.c.id))
        .where(skills_table.c.visibility == "public")
        .order_by(skills_table.c.download_count.desc(), skills_table.c.id)
        .limit(limit)
    )
    sample: list[dict] = []
    with engine.connect() as conn:
        skills = [dict(row._mapping) for row in conn.execute(skills_stmt).all()]
        for skill in skills:
            version_stmt = (
                sa.select(versions_table.c.s3_key)
                .where(versions_table.c.skill_id == skill["id"])
                .order_by(versions_table.c.created_at.desc(), versions_table.c.id)
                .limit(1)
            )
            row = conn.execute(version_stmt).first()
            if row is not None:
                sample.append({**skill, "s3_key": row.s3_key})
    return sample


def _classify_both(
    skill: dict,
    settings: Settings,
    taxonomy_fragment: str,
) -> dict:
    """Download one skill's SKILL.md and classify it with both backends."""
    s3 = create_s3_client(
        settings.aws_region,
        settings.aws_access_key_id,
        settings.aws_secret_access_key,
        settings.s3_endpoint_url,
    )
    zip_bytes = download_skill_zip(s3, settings.s3_bucket, skill["s3_key"])
    skill_md_content, _, _, _ = extract_for_evaluation(zip_bytes)
    body = extract_body(skill_md_content)

    result: dict = {
        "skill_id": str(skill["id"]),
        "skill": f"{skill['org_slug']}/{skill['name']}",
        "current_category": skill["category"],
    }
    backends = {
        "gemini": (create_gemini_client(settings.google_api_key), settings.gemini_model),
        "qwen": (create_openrouter_client(settings.openrouter_api_key), settings.openrouter_model),
    }
    for label, (client, model) in backends.items():
        raw = classify_skill(client, skill["name"], skill["description"] or "", body, taxonomy_fragment, model=model)
        parsed = parse_classification_response(raw)
        result[label] = parsed.category
        result[f"{label}_confidence"] = parsed.confidence
    result["agree"] = result["gemini"] == result["qwen"]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Gemini vs Qwen skill classification")
    parser.add_argument("--limit", type=int, default=100, help="Number of skills to sample (by downloads)")
    parser.add_argument("--workers", type=int, default=8, help="Parallel classification workers")
    parser.add_argument("--output", type=Path, default=Path("classification_comparison.jsonl"))
    parser.add_argument("--no-resume", action="store_true", help="Re-classify skills already in the output file")
    args = parser.parse_args()

    settings = create_settings()
    if not settings.google_api_key or not settings.openrouter_api_key:
        raise SystemExit("Both GOOGLE_API_KEY and OPENROUTER_API_KEY must be configured for a comparison")

    done: set[str] = set()
    if args.output.exists() and not args.no_resume:
        with args.output.open() as f:
            done = {json.loads(line)["skill_id"] for line in f if line.strip()}
        logger.info("Resuming: {} skills already compared", len(done))

    skills = [s for s in _fetch_sample(settings, args.limit) if str(s["id"]) not in done]
    logger.info("Comparing classification for {} skills", len(skills))
    taxonomy_fragment = build_taxonomy_prompt_fragment()

    with args.output.open("a") as out, ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_classify_both, s, settings, taxonomy_fragment): s for s in skills}
        for future in as_completed(futures):
            skill = futures[future]
            try:
                result = future.result()
            except Exception:
                logger.opt(exception=True).warning("Comparison failed for {}/{}", skill["org_slug"], skill["name"])
                continue
            out.write(json.dumps(result) + "\n")
            out.flush()
            logger.info(
                "{}: gemini={} qwen={} {}",
                result["skill"],
                result["gemini"],
                result["qwen"],
                "AGREE" if result["agree"] else "DISAGREE",
            )

    # Summary over the full output file (including prior runs)
    with args.output.open() as f:
        results = [json.loads(line) for line in f if line.strip()]
    agree = sum(1 for r in results if r["agree"])
    logger.info("Agreement: {}/{} ({:.0%})", agree, len(results), agree / len(results) if results else 0)
    for r in results:
        if not r["agree"]:
            logger.info("  DISAGREE {}: gemini={} qwen={}", r["skill"], r["gemini"], r["qwen"])


if __name__ == "__main__":
    main()
