# Skill-Scanner Integration Analysis

> Analysis of integrating [cisco-ai-defense/skill-scanner](https://github.com/cisco-ai-defense/skill-scanner) into the dhub server-side gauntlet pipeline as a full replacement for the current homegrown safety checks.

## Summary

Replace dhub's current gauntlet safety pipeline with `cisco-ai-skill-scanner` (Apache 2.0, published on PyPI as `cisco-ai-skill-scanner`). This gives us a single source of truth for safety evaluations backed by 90+ YARA/YAML signature rules, AST-based behavioral dataflow analysis, LLM-as-a-judge (via litellm, using our existing Gemini key), and a meta-analyzer for false positive reduction. Adopt the Cisco AITech threat taxonomy and expose full per-finding evaluation reports through the API and frontend.

---

## Part 1: Current dhub Gauntlet Pipeline

### What it does

The gauntlet pipeline lives in `server/src/decision_hub/domain/gauntlet.py` and is orchestrated by `registry_service.run_gauntlet_pipeline()`. It runs six checks:

1. **Manifest schema validation** (`check_manifest_schema`) — parses YAML frontmatter, verifies `name` and `description` exist
2. **Dependency audit** (`check_dependency_audit`) — checks lockfiles against a 3-package blocklist (`invoke`, `fabric`, `paramiko`)
3. **Embedded credential detection** (`check_embedded_credentials`) — two-layer:
   - Known-format regex (AWS keys, GitHub tokens, Slack, Stripe, Google, Anthropic, OpenAI, PEM, JWT) — always fail
   - Shannon entropy analysis on string literals — optional Gemini LLM judge review
4. **Safety scan** (`check_safety_scan`) — regex patterns for `subprocess`, `os.system`, `eval()`, `exec()`, `__import__()`, hardcoded credentials — optional Gemini LLM judge
5. **Prompt injection scan** (`check_prompt_safety`) — regex patterns for instruction overrides, role hijacks, memory wipes, zero-width unicode, exfiltration URLs, tool escalation markup — optional Gemini LLM judge + holistic body review
6. **Elevated permission detection** (`detect_elevated_permissions`) — regex for shell, network, fs_write, env_var usage

These produce `EvalResult` objects (pass/warn/fail) which are combined into a `GauntletReport` with a composite grade:
- **F** — any check failed
- **C** — any check warned (ambiguous)
- **B** — elevated permissions detected (but nothing failed/warned)
- **A** — all clear

### Where it's called (3 code paths)

1. **`POST /v1/publish`** — user uploads zip -> `extract_for_evaluation()` -> `run_gauntlet_pipeline()` -> grade -> publish or quarantine
2. **Crawler** (`scripts/crawler/processing.py`) — discovers SKILL.md in cloned repos -> same pipeline
3. **Tracker** (`domain/tracker_service.py`) — polls tracked repos -> same pipeline

All three funnel through `registry_service.run_gauntlet_pipeline()`.

### Current LLM integration

The gauntlet uses **Gemini** (via `infra/gemini.py`) as an LLM judge for three checks: safety scan, prompt safety, and credential entropy. The LLM is optional — if `google_api_key` is not set, checks run in "strict regex-only mode" where any regex hit is a failure.

Four callback factories in `registry_service.py` build the LLM judges:
- `_build_analyze_fn()` — code safety
- `_build_analyze_prompt_fn()` — prompt safety
- `_build_review_body_fn()` — holistic body review
- `_build_analyze_credential_fn()` — entropy credential review

### Why replace

- ~30 regex patterns total — limited coverage
- No AST/dataflow analysis — can't detect data flows from sources to sinks
- No YARA rules — misses many known malicious patterns
- No bytecode verification — can't detect tampered `.pyc` files
- No file type magic detection — relies on extensions
- No cross-file correlation
- No configurable policy system — all thresholds are hardcoded
- Single LLM provider (Gemini only via custom prompts)
- Custom LLM prompt maintenance burden — we're rolling our own judge prompts that skill-scanner has already refined with structured output schemas and AITech taxonomy alignment

---

## Part 2: skill-scanner Capabilities

### Detection engines

| Analyzer | Method | Scope | Requirements |
|----------|--------|-------|-------------|
| **Static** | 90+ YAML signatures + 14 YARA rules | All files | None |
| **Bytecode** | `.pyc` integrity verification | Python bytecode | None |
| **Pipeline** | Shell command taint analysis | Shell pipelines | None |
| **Behavioral** | AST dataflow analysis (source->sink tracking) | Python files | None |
| **LLM** | Semantic threat analysis with structured output | SKILL.md + scripts | API key (via litellm) |
| **Meta** | Second-pass LLM false-positive filtering | All findings | API key (via litellm) |
| **VirusTotal** | Hash-based malware detection | Binary files | API key |
| **AI Defense** | Cisco cloud-based AI scanning | Text content | API key |
| **Trigger** | Overly-generic description detection | SKILL.md | None |

### Threat taxonomy (Cisco AITech)

16 machine-readable threat categories:
`prompt_injection`, `command_injection`, `data_exfiltration`, `unauthorized_tool_use`, `obfuscation`, `hardcoded_secrets`, `social_engineering`, `resource_abuse`, `policy_violation`, `malware`, `harmful_content`, `skill_discovery_abuse`, `transitive_trust_abuse`, `autonomy_abuse`, `tool_chaining_abuse`, `unicode_steganography`, `supply_chain_attack`

Each finding also carries AITech codes (e.g., `AITech-9.1` for command injection, `AITech-1.1` for direct prompt injection) that map to the full Cisco AI Security Framework taxonomy.

### Severity model

`CRITICAL > HIGH > MEDIUM > LOW > INFO > SAFE`

`ScanResult.is_safe` = no CRITICAL or HIGH findings.

### LLM analyzer details

The LLM analyzer (`skill_scanner/core/analyzers/llm_analyzer.py`) uses **litellm** for universal provider support. It detects the provider from the model string:

- `gemini-2.0-flash` or `gemini/2.0-flash` -> Google AI Studio (via `google-genai` SDK directly, or via litellm)
- `claude-3-5-sonnet-20241022` -> Anthropic
- `gpt-4o` -> OpenAI
- `vertex_ai/gemini-1.5-pro` -> Vertex AI
- `bedrock/anthropic.claude-v2` -> AWS Bedrock

For Gemini specifically, it checks if `google-genai` is available and uses the native SDK; otherwise falls back to litellm. The API key is resolved from the `SKILL_SCANNER_LLM_API_KEY` environment variable, or can be passed directly via the `api_key` constructor parameter.

This means we can pass our existing `google_api_key` directly:

```python
from skill_scanner.core.analyzers.llm_analyzer import LLMAnalyzer

llm_analyzer = LLMAnalyzer(
    model="gemini-2.0-flash",
    api_key=settings.google_api_key,
)
```

### Meta-analyzer details

The meta-analyzer (`skill_scanner/core/analyzers/meta_analyzer.py`) runs *after* all other analyzers and reviews the collective findings to:
- Filter false positives based on contextual understanding
- Prioritize findings by actual exploitability
- Correlate related findings across analyzers
- Detect threats other analyzers may have missed

It uses the same litellm infrastructure, so the same API key works. It returns a `MetaAnalysisResult` with `validated_findings`, `false_positives`, `missed_threats`, `correlations`, and `overall_risk_assessment`.

### Policy system

YAML-based `ScanPolicy` with:
- **Presets**: `strict`, `balanced` (default), `permissive`
- **`disabled_rules`**: suppress specific rule IDs
- **`severity_overrides`**: adjust severity per rule
- **Analyzability thresholds**: flag opaque files (fail-closed)
- **File classification**: inert extensions, hidden file handling
- **Finding output**: dedup, collapse same-issue across analyzers

### Python SDK

```python
from skill_scanner import SkillScanner
from skill_scanner.core.analyzers.llm_analyzer import LLMAnalyzer
from skill_scanner.core.analyzers.behavioral_analyzer import BehavioralAnalyzer
from skill_scanner.core.analyzers.meta_analyzer import MetaAnalyzer
from skill_scanner.core.analyzer_factory import build_analyzers
from skill_scanner.core.scan_policy import ScanPolicy

policy = ScanPolicy.from_preset("balanced")
analyzers = build_analyzers(
    policy,
    use_behavioral=True,
    use_llm=True,
    llm_provider="anthropic",  # or pass model= directly
)
scanner = SkillScanner(analyzers=analyzers, policy=policy)
result = scanner.scan_skill("/path/to/skill")

result.is_safe              # bool: no CRITICAL/HIGH findings
result.max_severity         # Severity enum
result.findings             # list[Finding]
result.analyzability_score  # float (0-100%)
result.to_dict()            # JSON-serializable dict (compatible with mcp-scanner-plugin)
```

### Input requirement: directory path

skill-scanner's `SkillLoader` requires a **directory path** on disk. It walks the filesystem, reads files, and uses `magika` for ML-based file type detection. This differs from dhub's in-memory approach.

**Implication**: We need to extract the zip to a temp directory before scanning.

---

## Part 3: skill-scanner "evals" vs dhub "evals"

These are completely disjoint concepts that happen to share the word "eval":

### dhub evals (agent assessments)

dhub's eval system (`domain/evals.py`, `infra/modal_client.py`) is an **agent-in-the-loop functional testing** framework:
- Spins up a Modal sandbox with an AI agent (Claude Code, etc.)
- Feeds it prompts from `evals/*.yaml` case files bundled with the skill
- Captures agent stdout/stderr/exit code
- Uses an LLM judge (Anthropic) to evaluate whether the agent's output meets criteria
- Produces pass/fail verdicts per case, stored as `eval_reports` in the DB
- Used for functional correctness assessment of published skills

### skill-scanner evals (scanner accuracy benchmarks)

skill-scanner's eval framework (`evals/`) is a **scanner self-test** suite:
- Curated set of intentionally safe and malicious skills with `_expected.json` ground truth
- Runs the scanner against them, compares actual findings vs expected findings
- Computes precision, recall, F1, accuracy metrics
- Used to validate scanner detection quality and prevent regressions

**They don't overlap at all.** dhub evals test whether a *skill works correctly* with an agent. skill-scanner evals test whether the *scanner detects threats correctly*. We don't need to integrate skill-scanner's eval framework into dhub — it's an internal development tool for the scanner itself.

However, the curated malicious skills in `evals/skills/` (backdoors, command injection, data exfiltration, obfuscation, prompt injection, etc.) are useful as **test fixtures** for validating our integration. We can use them to confirm the bridge module correctly detects known threats.

---

## Part 4: Integration Design

### Approach: Full replacement with adapter bridge

Replace the gauntlet pipeline entirely. skill-scanner becomes the SSoT for safety evaluations. The bridge module adapts between dhub's zip-based publish flow and skill-scanner's directory-based scanner.

### Architecture

```
                    ┌─────────────────────────────────────────────────┐
                    │           registry_service.py                    │
                    │       run_safety_scan()  [replaces gauntlet]     │
                    ├─────────────────────────────────────────────────┤
                    │                                                  │
                    │  1. check_manifest_schema()  [keep — dhub-      │
                    │     specific manifest requirements]              │
                    │                                                  │
                    │  2. check_dependency_audit()  [keep — not        │
                    │     covered by skill-scanner]                    │
                    │                                                  │
                    │  3. run_skill_scanner()  [NEW — replaces all     │
                    │     regex checks, LLM judges, prompt safety,     │
                    │     credential detection]                        │
                    │     ↓ ScanResult (findings, is_safe, severity)   │
                    │                                                  │
                    │  4. Map to grade + build full report             │
                    │                                                  │
                    └─────────────────────────────────────────────────┘
                                        │
                    ┌───────────────────┴───────────────────┐
                    │     skill_scanner_bridge.py [NEW]      │
                    ├───────────────────────────────────────┤
                    │                                        │
                    │  1. Extract zip → temp dir             │
                    │  2. Configure ScanPolicy (balanced)    │
                    │  3. Build analyzers:                   │
                    │     - static + bytecode + pipeline     │
                    │     - behavioral                       │
                    │     - LLM (Gemini via google_api_key)  │
                    │     - meta (FP filtering)              │
                    │  4. SkillScanner.scan_skill()          │
                    │  5. Return ScanResult.to_dict()        │
                    │  6. Cleanup temp dir                   │
                    │                                        │
                    └────────────────────────────────────────┘
```

### What gets removed from gauntlet.py

| Current check | Replacement | Notes |
|---------------|-------------|-------|
| `_SUSPICIOUS_PATTERNS` + `check_safety_scan()` | skill-scanner static analyzer (90+ rules) | Superset of our 6 regex patterns |
| `_CREDENTIAL_PATTERNS` + `check_embedded_credentials()` | skill-scanner `hardcoded_secrets` rules + YARA `credential_harvesting_generic.yara` | Superset including entropy analysis |
| `_PROMPT_INJECTION_PATTERNS` + `check_prompt_safety()` | skill-scanner `prompt_injection` rules + YARA `prompt_injection_generic.yara` + `indirect_prompt_injection_generic.yara` + `coercive_injection_generic.yara` | Much broader coverage |
| `detect_elevated_permissions()` | skill-scanner `unauthorized_tool_use` category + `allowed_tools_checks.py` | Similar concept, richer detection |
| `_build_analyze_fn()` and 3 other Gemini callbacks | skill-scanner `LLMAnalyzer` (uses same Gemini key via litellm) | Structured output with AITech taxonomy |
| `compute_grade()` | New grade mapping from `ScanResult` | See below |

### What stays

| Check | Why |
|-------|-----|
| `check_manifest_schema()` | dhub has specific manifest requirements (name + description in YAML frontmatter) that skill-scanner's loader validates differently. Keep for the 422 error message consistency. |
| `check_dependency_audit()` | skill-scanner doesn't scan lockfiles against a blocklist. Keep this simple 3-package check. |
| `parse_test_cases()` / `evaluate_test_results()` | Functional test evaluation logic — unrelated to safety scanning. |

### Grade mapping

Adopt skill-scanner's severity model as the primary signal, map to dhub's existing A/B/C/F grades for backward compatibility:

```
CRITICAL or HIGH finding  →  F (fail, quarantine)
MEDIUM finding            →  C (warn, publish with warning)
LOW or INFO only          →  A (pass)
```

Note: the B grade (elevated permissions, no failures) goes away. skill-scanner's `unauthorized_tool_use` category covers the same concept but as actual findings with severity levels, which is cleaner.

### Audit log: full scanner report

Store the complete `ScanResult.to_dict()` in the audit log. This includes:
- `is_safe`, `max_severity`, `findings_count`
- Full `findings[]` array with per-finding: `rule_id`, `category`, `severity`, `title`, `description`, `file_path`, `line_number`, `snippet`, `remediation`, `analyzer`, `metadata` (AITech codes)
- `analyzers_used[]`
- `analyzability_score` and `analyzability_details`
- `scan_metadata` (policy fingerprint, LLM assessment)

This replaces the current sparse `check_results` (just check name + pass/fail) with rich, actionable data.

### LLM integration via litellm

Since we already call Gemini and have `google_api_key` in settings, wiring it into skill-scanner's LLM analyzer is straightforward:

```python
from skill_scanner.core.analyzers.llm_analyzer import LLMAnalyzer
from skill_scanner.core.analyzers.meta_analyzer import MetaAnalyzer

# LLM analyzer — uses our existing Gemini key
llm = LLMAnalyzer(
    model=settings.gemini_model,  # "gemini-2.0-flash"
    api_key=settings.google_api_key,
)

# Meta-analyzer — same key, reduces false positives
meta = MetaAnalyzer(
    model=settings.gemini_model,
    api_key=settings.google_api_key,
)
```

skill-scanner's `ProviderConfig` detects `gemini` in the model name and uses the `google-genai` SDK directly (which is already a dependency of skill-scanner). No additional API keys or provider configuration needed.

The LLM analyzer produces findings with structured AITech taxonomy codes and semantic analysis. The meta-analyzer then reviews all findings (from static + behavioral + LLM) and filters false positives. This replaces our four custom Gemini callback functions (`_build_analyze_fn`, `_build_analyze_prompt_fn`, `_build_review_body_fn`, `_build_analyze_credential_fn`) with a more sophisticated pipeline.

---

## Part 5: Technical Considerations

### Dependency weight

skill-scanner adds these dependencies:

| Package | Size | Purpose |
|---------|------|---------|
| `yara-x` | ~15 MB wheel | Rust-based YARA engine |
| `magika` | ~50 MB model | ML file type detection |
| `litellm` | ~10 MB | LLM proxy (multi-provider) |
| `python-frontmatter` | <1 MB | SKILL.md parsing |
| `confusable-homoglyphs` | ~2 MB | Unicode attack detection |
| `oletools` | ~5 MB | Office document malware |
| `pdfid` | <1 MB | PDF structure analysis |
| `anthropic`, `openai` | ~5 MB each | LLM clients (litellm deps) |

**Total**: ~90-100 MB additional in the Modal container image.

**Mitigation**:
- Install without `[all]` extras (skip Bedrock/Vertex/Azure clients)
- skill-scanner lazy-loads via `__getattr__` — import cost is minimal until first scan
- Profile Modal cold-start impact (currently ~30-60s; may add ~5-10s)

### YARA binary dependency

`yara-x` ships pre-built wheels for Linux x86_64 + Python 3.10-3.13. Modal uses Linux x86_64, so pip install should work. Verify during Modal image build.

### Disk I/O for scanning

skill-scanner requires extracting the zip to a temp directory. The bridge module handles this:

```python
import io, tempfile, zipfile
from pathlib import Path
from skill_scanner import SkillScanner
from skill_scanner.core.scan_policy import ScanPolicy

def scan_skill_zip(zip_bytes: bytes, settings) -> dict:
    with tempfile.TemporaryDirectory(prefix="skill_scan_") as tmp:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(tmp)
        skill_dir = _find_skill_md_parent(Path(tmp))
        scanner = _build_scanner(settings)
        result = scanner.scan_skill(skill_dir)
        return result.to_dict()
```

Modal containers have writable `/tmp`. Fine for ephemeral scan artifacts.

### Scan policy

Start with `ScanPolicy.from_preset("balanced")`. Over time, create a custom `dhub_scan_policy.yaml` in the server package to tune disabled rules and severity overrides based on observed false positive rates.

### DB schema

The `audit_log` table already stores `check_results` (JSONB) and `llm_reasoning` (JSONB). The full `ScanResult.to_dict()` can go into `llm_reasoning` initially (it's already a catch-all JSON field). For a cleaner separation, add a `scanner_report JSONB` column via migration.

### Performance

| Operation | Time |
|-----------|------|
| Extract zip to temp dir | <100ms |
| Core analyzers (static + bytecode + pipeline) | <500ms |
| Behavioral analyzer | 200ms-1s |
| LLM analyzer (Gemini) | 2-5s |
| Meta-analyzer (Gemini) | 2-5s |
| **Total (all analyzers)** | **~5-12s** |

Current gauntlet with Gemini: 3-10s. Comparable wall time, but vastly deeper analysis.

### License

Apache 2.0. Fully compatible — it's a permissive license. No copyleft concerns, no attribution issues beyond including the license text (which pip handles automatically for dependencies). Same license family as FastAPI, Pydantic, and most of our other dependencies.

---

## Part 6: Files to Modify

| File | Change |
|------|--------|
| `server/pyproject.toml` | Add `cisco-ai-skill-scanner` dependency |
| `server/src/decision_hub/domain/skill_scanner_bridge.py` | **New**: adapter module (extract zip, configure scanner, run, map results) |
| `server/src/decision_hub/api/registry_service.py` | Replace `run_gauntlet_pipeline()` with new function that calls bridge. Remove `_build_analyze_fn` and siblings. |
| `server/src/decision_hub/domain/gauntlet.py` | Gut most of file: remove `_SUSPICIOUS_PATTERNS`, `_CREDENTIAL_PATTERNS`, `_PROMPT_INJECTION_PATTERNS`, `check_safety_scan`, `check_embedded_credentials`, `check_prompt_safety`, `detect_elevated_permissions`. Keep `check_manifest_schema`, `check_dependency_audit`, test case logic. |
| `server/src/decision_hub/models.py` | Adopt skill-scanner's severity/category types or add mapping types |
| `server/src/decision_hub/infra/gemini.py` | Remove `analyze_code_safety`, `analyze_prompt_safety`, `review_prompt_body_safety`, `analyze_credential_entropy` (replaced by skill-scanner LLM analyzer) |
| `server/modal_app.py` | Add `cisco-ai-skill-scanner` to Modal image deps |
| `server/migrations/YYYYMMDD_HHMMSS_add_scanner_report.sql` | New `scanner_report JSONB` column on `audit_log` |
| `server/tests/test_skill_scanner_bridge.py` | **New**: unit tests for bridge |
| `server/tests/test_gauntlet.py` | Update tests for removed checks |
| `frontend/` | Expose per-finding details in skill detail page (later PR) |

### Code to delete

- `gauntlet.py`: ~600 of 851 lines (all pattern definitions, credential/safety/prompt checks, elevated permission detection)
- `registry_service.py`: ~100 lines (four `_build_analyze_*_fn` factories)
- `gemini.py`: ~200 lines (four analysis functions)

**Net**: Replace ~900 lines of custom safety scanning code with ~100 lines of bridge code + a battle-tested third-party scanner.

---

## Part 7: Implementation Steps

1. **Add dependency** — `cisco-ai-skill-scanner` in `server/pyproject.toml`, verify Modal image builds
2. **Create bridge module** — `skill_scanner_bridge.py` with `scan_skill_zip()` function
3. **Rewrite `run_gauntlet_pipeline()`** — call bridge instead of old checks, map results to grade
4. **DB migration** — add `scanner_report` JSONB column to `audit_log`
5. **Remove dead code** — pattern definitions, LLM callback factories, Gemini analysis functions
6. **Update tests** — bridge unit tests, update gauntlet tests
7. **Update Modal image** — add dependency, verify cold start
8. **Frontend** — expose scanner findings in skill detail page (separate PR)
