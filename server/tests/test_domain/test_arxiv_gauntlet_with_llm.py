"""Side-by-side benchmark: regex-only vs full LLM pipeline.

Runs the SAME 31+31 test cases from test_arxiv_gauntlet.py through
the gauntlet with real Gemini LLM calls enabled, then compares
detection rates against the regex-only baseline.

Requires GOOGLE_API_KEY in the environment (loaded from server/.env.dev).
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

from decision_hub.domain.gauntlet import run_static_checks
from decision_hub.infra.gemini import (
    analyze_code_safety,
    analyze_credential_entropy,
    analyze_prompt_safety,
    create_gemini_client,
    review_prompt_body_safety,
)

# Load sibling test module dynamically (pytest import mode doesn't expose it)
_sibling = Path(__file__).with_name("test_arxiv_gauntlet.py")
_spec = importlib.util.spec_from_file_location("test_arxiv_gauntlet", _sibling)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["test_arxiv_gauntlet"] = _mod
_spec.loader.exec_module(_mod)

MaliciousSkillCase = _mod.MaliciousSkillCase
_build_test_set = _mod._build_test_set
_build_evaded_test_set = _mod._build_evaded_test_set
_run_gauntlet_no_llm = _mod._run_gauntlet_no_llm

# ---------------------------------------------------------------------------
# API key loading
# ---------------------------------------------------------------------------

# Try worktree-local path first, then fall back to main repo
_env_dev_path = Path(__file__).resolve().parents[2] / ".env.dev"
if not _env_dev_path.exists():
    # Worktrees share the same parent repo; look in the original checkout
    _env_dev_path = Path(__file__).resolve().parents[5] / "server" / ".env.dev"
load_dotenv(_env_dev_path)

_HAS_API_KEY = bool(os.environ.get("GOOGLE_API_KEY"))

pytestmark = pytest.mark.skipif(
    not _HAS_API_KEY,
    reason="GOOGLE_API_KEY not set (load from server/.env.dev or environment)",
)

# ---------------------------------------------------------------------------
# LLM-enabled gauntlet runner
# ---------------------------------------------------------------------------


def _run_gauntlet_with_llm(case: MaliciousSkillCase) -> dict:
    """Run a single case through the gauntlet WITH real Gemini LLM calls."""
    api_key = os.environ["GOOGLE_API_KEY"]
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    client = create_gemini_client(api_key)

    def analyze_fn(snippets, source_files, skill_name, skill_description):
        return analyze_code_safety(client, snippets, source_files, skill_name, skill_description, model=model)

    def analyze_prompt_fn(prompt_hits, skill_name, skill_description):
        return analyze_prompt_safety(client, prompt_hits, skill_name, skill_description, model=model)

    def review_body_fn(body, skill_name, skill_description):
        return review_prompt_body_safety(client, body, skill_name, skill_description, model=model)

    def analyze_credential_fn(entropy_hits, skill_name, skill_description):
        return analyze_credential_entropy(client, entropy_hits, skill_name, skill_description, model=model)

    # Parse skill name/description from frontmatter
    skill_name = ""
    skill_description = ""
    if "name: " in case.skill_md_content:
        skill_name = case.skill_md_content.split("name: ")[1].split("\n")[0].strip()
    if "description: " in case.skill_md_content:
        skill_description = case.skill_md_content.split("description: ")[1].split("\n")[0].strip()

    report = run_static_checks(
        skill_md_content=case.skill_md_content,
        lockfile_content=case.lockfile_content,
        source_files=case.source_files,
        skill_name=skill_name,
        skill_description=skill_description,
        analyze_fn=analyze_fn,
        skill_md_body=case.skill_md_body,
        allowed_tools=case.allowed_tools,
        analyze_prompt_fn=analyze_prompt_fn,
        review_body_fn=review_body_fn,
        analyze_credential_fn=analyze_credential_fn,
    )

    failed_checks = [r for r in report.results if r.severity == "fail"]
    warned_checks = [r for r in report.results if r.severity == "warn"]

    return {
        "case_id": case.case_id,
        "paper_ref": case.paper_ref,
        "patterns": case.patterns,
        "archetype": case.archetype,
        "level": case.level,
        "grade": report.grade,
        "caught": report.grade == "F",
        "passed_checks": sum(1 for r in report.results if r.severity == "pass"),
        "failed_checks": [r.check_name for r in failed_checks],
        "warned_checks": [r.check_name for r in warned_checks],
        "total_checks": len(report.results),
        "details": [{"check": r.check_name, "severity": r.severity, "message": r.message} for r in report.results],
    }


# ---------------------------------------------------------------------------
# Helpers for formatting comparison tables
# ---------------------------------------------------------------------------


def _print_separator(char: str = "=", width: int = 80) -> None:
    print(char * width)


def _print_level_breakdown(results: list[dict], label: str) -> None:
    """Print per-level breakdown for a set of results."""
    print(f"\n  Per-Level ({label}):")
    for level in (1, 2, 3):
        level_results = [r for r in results if r["level"] == level]
        if not level_results:
            continue
        level_caught = sum(1 for r in level_results if r["caught"])
        rate = level_caught / len(level_results) * 100
        print(f"    Level {level}: {level_caught}/{len(level_results)} ({rate:.1f}%)")


def _print_archetype_breakdown(results: list[dict], label: str) -> None:
    """Print per-archetype breakdown for a set of results."""
    print(f"\n  Per-Archetype ({label}):")
    for archetype in ("data_thief", "agent_hijacker", "hybrid", "platform_native"):
        arch_results = [r for r in results if r["archetype"] == archetype]
        if not arch_results:
            continue
        arch_caught = sum(1 for r in arch_results if r["caught"])
        rate = arch_caught / len(arch_results) * 100
        print(f"    {archetype}: {arch_caught}/{len(arch_results)} ({rate:.1f}%)")


def _print_pattern_breakdown(results: list[dict], label: str) -> None:
    """Print per-pattern breakdown for a set of results."""
    print(f"\n  Per-Pattern ({label}):")
    pattern_stats: dict[str, dict[str, int]] = {}
    for r in results:
        for p in r["patterns"]:
            if p not in pattern_stats:
                pattern_stats[p] = {"total": 0, "caught": 0}
            pattern_stats[p]["total"] += 1
            if r["caught"]:
                pattern_stats[p]["caught"] += 1

    for p in sorted(pattern_stats.keys()):
        s = pattern_stats[p]
        rate = s["caught"] / s["total"] * 100
        print(f"    {p}: {s['caught']}/{s['total']} ({rate:.1f}%)")


# ---------------------------------------------------------------------------
# Main benchmark test
# ---------------------------------------------------------------------------


class TestSideBySideComparison:
    """Run both original and evaded sets in BOTH modes and print comparison."""

    def test_full_comparison(self):
        """Side-by-side: regex-only vs full pipeline (with LLM)."""
        original_cases = _build_test_set()
        evaded_cases = _build_evaded_test_set()

        # --- Regex-only baseline ---
        print("\n[1/4] Running original set with regex-only...")
        orig_regex = [_run_gauntlet_no_llm(c) for c in original_cases]

        print("[2/4] Running evaded set with regex-only...")
        evaded_regex = [_run_gauntlet_no_llm(c) for c in evaded_cases]

        # --- LLM-enabled pipeline ---
        print("[3/4] Running original set with LLM (this may take a few minutes)...")
        orig_llm = [_run_gauntlet_with_llm(c) for c in original_cases]

        print("[4/4] Running evaded set with LLM (this may take a few minutes)...")
        evaded_llm = [_run_gauntlet_with_llm(c) for c in evaded_cases]

        # --- Compute stats ---
        orig_regex_caught = sum(1 for r in orig_regex if r["caught"])
        orig_llm_caught = sum(1 for r in orig_llm if r["caught"])
        evaded_regex_caught = sum(1 for r in evaded_regex if r["caught"])
        evaded_llm_caught = sum(1 for r in evaded_llm if r["caught"])

        orig_total = len(original_cases)
        evaded_total = len(evaded_cases)

        # ===================================================================
        # MAIN COMPARISON TABLE
        # ===================================================================
        print("\n")
        _print_separator()
        print("SIDE-BY-SIDE: REGEX-ONLY vs FULL PIPELINE (WITH LLM)")
        _print_separator()
        print(f"{'':20s} | {'Regex-Only':>12s} | {'With LLM':>12s} | {'Delta':>8s}")
        print(f"{'-' * 20}-+-{'-' * 12}-+-{'-' * 12}-+-{'-' * 8}")

        orig_delta = orig_llm_caught - orig_regex_caught
        evaded_delta = evaded_llm_caught - evaded_regex_caught

        print(
            f"{'Original (' + str(orig_total) + ')':20s} | "
            f"{orig_regex_caught:>5d}/{orig_total:<5d} | "
            f"{orig_llm_caught:>5d}/{orig_total:<5d} | "
            f"{'+' if orig_delta >= 0 else ''}{orig_delta:>6d}"
        )
        print(
            f"{'Evaded (' + str(evaded_total) + ')':20s} | "
            f"{evaded_regex_caught:>5d}/{evaded_total:<5d} | "
            f"{evaded_llm_caught:>5d}/{evaded_total:<5d} | "
            f"{'+' if evaded_delta >= 0 else ''}{evaded_delta:>6d}"
        )
        _print_separator("-")

        # ===================================================================
        # DETAILED BREAKDOWNS (LLM-enabled results)
        # ===================================================================
        print("\n")
        _print_separator()
        print("LLM-ENABLED DETAILED BREAKDOWNS")
        _print_separator()

        _print_level_breakdown(orig_llm, "Original")
        _print_level_breakdown(evaded_llm, "Evaded")

        _print_archetype_breakdown(orig_llm, "Original")
        _print_archetype_breakdown(evaded_llm, "Evaded")

        _print_pattern_breakdown(orig_llm, "Original")
        _print_pattern_breakdown(evaded_llm, "Evaded")

        # ===================================================================
        # LLM RESCUE LIST: caught by LLM but missed by regex
        # ===================================================================
        print("\n")
        _print_separator()
        print("LLM RESCUE LIST (caught with LLM but missed by regex-only)")
        _print_separator()

        # Build lookup for regex results
        orig_regex_by_id = {r["case_id"]: r for r in orig_regex}
        evaded_regex_by_id = {r["case_id"]: r for r in evaded_regex}

        rescued_original = []
        for r in orig_llm:
            regex_r = orig_regex_by_id[r["case_id"]]
            if r["caught"] and not regex_r["caught"]:
                rescued_original.append(r)

        rescued_evaded = []
        for r in evaded_llm:
            regex_r = evaded_regex_by_id[r["case_id"]]
            if r["caught"] and not regex_r["caught"]:
                rescued_evaded.append(r)

        if rescued_original:
            print(f"\n  Original set ({len(rescued_original)} rescued):")
            for r in rescued_original:
                print(
                    f"    {r['case_id']} (L{r['level']}, {r['archetype']}) " f"-- patterns: {', '.join(r['patterns'])}"
                )
                print(f"      Failed checks: {r['failed_checks']}")
        else:
            print("\n  Original set: 0 rescued (regex already caught everything it could)")

        if rescued_evaded:
            print(f"\n  Evaded set ({len(rescued_evaded)} rescued):")
            for r in rescued_evaded:
                print(
                    f"    {r['case_id']} (L{r['level']}, {r['archetype']}) " f"-- patterns: {', '.join(r['patterns'])}"
                )
                print(f"      Failed checks: {r['failed_checks']}")
        else:
            print("\n  Evaded set: 0 rescued")

        # ===================================================================
        # REGRESSIONS: caught by regex but missed by LLM
        # ===================================================================
        print("\n")
        _print_separator()
        print("REGRESSIONS (caught by regex-only but MISSED with LLM)")
        _print_separator()

        regressions_original = []
        for r in orig_llm:
            regex_r = orig_regex_by_id[r["case_id"]]
            if not r["caught"] and regex_r["caught"]:
                regressions_original.append(r)

        regressions_evaded = []
        for r in evaded_llm:
            regex_r = evaded_regex_by_id[r["case_id"]]
            if not r["caught"] and regex_r["caught"]:
                regressions_evaded.append(r)

        if regressions_original:
            print(f"\n  Original set ({len(regressions_original)} regressions):")
            for r in regressions_original:
                print(f"    {r['case_id']} (L{r['level']}, {r['archetype']}) " f"grade={r['grade']}")
                for d in r["details"]:
                    marker = "FAIL" if d["severity"] == "fail" else "WARN" if d["severity"] == "warn" else "pass"
                    print(f"      [{marker}] {d['check']}: {d['message'][:120]}")
        else:
            print("\n  Original set: 0 regressions")

        if regressions_evaded:
            print(f"\n  Evaded set ({len(regressions_evaded)} regressions):")
            for r in regressions_evaded:
                print(f"    {r['case_id']} (L{r['level']}, {r['archetype']}) " f"grade={r['grade']}")
        else:
            print("\n  Evaded set: 0 regressions")

        # ===================================================================
        # STILL EVADING: missed in BOTH modes
        # ===================================================================
        print("\n")
        _print_separator()
        print("STILL EVADING EVEN WITH LLM")
        _print_separator()

        still_evading_orig = [r for r in orig_llm if not r["caught"]]
        still_evading_evaded = [r for r in evaded_llm if not r["caught"]]

        if still_evading_orig:
            print(f"\n  Original set ({len(still_evading_orig)} still missed):")
            for r in still_evading_orig:
                print(
                    f"    {r['case_id']} (L{r['level']}, {r['archetype']}) "
                    f"grade={r['grade']} -- patterns: {', '.join(r['patterns'])}"
                )
                for d in r["details"]:
                    marker = "FAIL" if d["severity"] == "fail" else "WARN" if d["severity"] == "warn" else "pass"
                    print(f"      [{marker}] {d['check']}: {d['message'][:120]}")
        else:
            print("\n  Original set: 0 missed (100% detection)")

        if still_evading_evaded:
            print(f"\n  Evaded set ({len(still_evading_evaded)} still missed):")
            for r in still_evading_evaded:
                print(
                    f"    {r['case_id']} (L{r['level']}, {r['archetype']}) "
                    f"grade={r['grade']} -- patterns: {', '.join(r['patterns'])}"
                )
                for d in r["details"]:
                    marker = "FAIL" if d["severity"] == "fail" else "WARN" if d["severity"] == "warn" else "pass"
                    print(f"      [{marker}] {d['check']}: {d['message'][:120]}")
        else:
            print("\n  Evaded set: 0 missed (100% detection)")

        # ===================================================================
        # PER-CASE DETAIL TABLE
        # ===================================================================
        print("\n")
        _print_separator()
        print("PER-CASE RESULTS (Evaded Set)")
        _print_separator()
        print(f"  {'Case ID':<40s} {'Regex':>6s} {'LLM':>6s} {'Rescued':>8s}")
        print(f"  {'-' * 40} {'-' * 6} {'-' * 6} {'-' * 8}")

        for r_llm, r_regex in zip(evaded_llm, evaded_regex, strict=False):
            regex_mark = "F" if r_regex["caught"] else r_regex["grade"]
            llm_mark = "F" if r_llm["caught"] else r_llm["grade"]
            rescued = "YES" if r_llm["caught"] and not r_regex["caught"] else ""
            print(f"  {r_llm['case_id']:<40s} {regex_mark:>6s} {llm_mark:>6s} {rescued:>8s}")

        # ===================================================================
        # FINAL SUMMARY
        # ===================================================================
        print("\n")
        _print_separator("=")
        print("FINAL SUMMARY")
        _print_separator("=")
        print(
            f"  Original set:  regex={orig_regex_caught}/{orig_total}  "
            f"LLM={orig_llm_caught}/{orig_total}  "
            f"delta={'+' if orig_delta >= 0 else ''}{orig_delta}"
        )
        print(
            f"  Evaded set:    regex={evaded_regex_caught}/{evaded_total}  "
            f"LLM={evaded_llm_caught}/{evaded_total}  "
            f"delta={'+' if evaded_delta >= 0 else ''}{evaded_delta}"
        )
        print(f"  Total rescued (original): {len(rescued_original)}")
        print(f"  Total rescued (evaded):   {len(rescued_evaded)}")
        print(f"  Total regressions (orig): {len(regressions_original)}")
        print(f"  Total regressions (evad): {len(regressions_evaded)}")
        _print_separator("=")

        # Assertion: LLM should add value for evaded cases
        evaded_llm_rate = evaded_llm_caught / evaded_total * 100
        assert evaded_llm_rate > 0, (
            f"LLM-enabled detection rate on evaded set is {evaded_llm_rate:.1f}%, "
            f"expected > 0% to prove LLM adds value"
        )
