# Skill-Scanner Integration Analysis

> Analysis of integrating [cisco-ai-defense/skill-scanner](https://github.com/cisco-ai-defense/skill-scanner) into the dhub server-side gauntlet pipeline.

## Summary

Integrate `cisco-ai-skill-scanner` (Apache 2.0, published on PyPI) into the dhub server to replace or augment the current homegrown gauntlet safety pipeline with a multi-engine, policy-driven security scanner backed by YARA rules, behavioral dataflow analysis, and LLM-as-a-judge.

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

1. **`POST /v1/publish`** — user uploads zip → `extract_for_evaluation()` → `run_gauntlet_pipeline()` → grade → publish or quarantine
2. **Crawler** (`scripts/crawler/processing.py`) — discovers SKILL.md in cloned repos → same pipeline
3. **Tracker** (`domain/tracker_service.py`) — polls tracked repos → same pipeline

All three funnel through `registry_service.run_gauntlet_pipeline()`.

### Current LLM integration

The gauntlet uses **Gemini** (via `infra/gemini.py`) as an LLM judge for three checks: safety scan, prompt safety, and credential entropy. The LLM is optional — if `google_api_key` is not set, checks run in "strict regex-only mode" where any regex hit is a failure.

Four callback factories in `registry_service.py` build the LLM judges:
- `_build_analyze_fn()` — code safety
- `_build_analyze_prompt_fn()` — prompt safety
- `_build_review_body_fn()` — holistic body review
- `_build_analyze_credential_fn()` — entropy credential review

### Strengths of the current system

- Simple, predictable, fast (~3-10s with LLM, <1s without)
- Fail-closed: LLM not covering a finding → treated as dangerous
- Tightly integrated with dhub's grade/audit/quarantine system
- No heavy dependencies

### Weaknesses

- ~30 regex patterns total — limited coverage
- No AST/dataflow analysis — can't detect data flows from sources to sinks
- No YARA rules — misses many known malicious patterns
- No bytecode verification — can't detect tampered `.pyc` files
- No file type magic detection — relies on extensions
- No cross-file correlation
- No configurable policy system — all thresholds are hardcoded
- Single LLM provider (Gemini only)

---

## Part 2: skill-scanner Capabilities

### Detection engines

| Analyzer | Method | Scope | Requirements |
|----------|--------|-------|-------------|
| **Static** | 90+ YAML signatures + 14 YARA rules | All files | None |
| **Bytecode** | `.pyc` integrity verification | Python bytecode | None |
| **Pipeline** | Shell command taint analysis | Shell pipelines | None |
| **Behavioral** | AST dataflow analysis (source→sink tracking) | Python files | None |
| **LLM** | Semantic threat analysis with structured output | SKILL.md + scripts | API key |
| **Meta** | Second-pass LLM false-positive filtering | All findings | API key |
| **VirusTotal** | Hash-based malware detection | Binary files | API key |
| **AI Defense** | Cisco cloud-based AI scanning | Text content | API key |
| **Trigger** | Overly-generic description detection | SKILL.md | None |

### Threat taxonomy

skill-scanner uses the Cisco AITech threat taxonomy with 16 categories:
`prompt_injection`, `command_injection`, `data_exfiltration`, `unauthorized_tool_use`, `obfuscation`, `hardcoded_secrets`, `social_engineering`, `resource_abuse`, `policy_violation`, `malware`, `harmful_content`, `skill_discovery_abuse`, `transitive_trust_abuse`, `autonomy_abuse`, `tool_chaining_abuse`, `unicode_steganography`, `supply_chain_attack`

### Severity model

`CRITICAL > HIGH > MEDIUM > LOW > INFO > SAFE`

`ScanResult.is_safe` = no CRITICAL or HIGH findings.

### Policy system

YAML-based `ScanPolicy` with:
- **Presets**: `strict`, `balanced` (default), `permissive`
- **`disabled_rules`**: suppress specific rule IDs
- **`severity_overrides`**: adjust severity per rule
- **Analyzability thresholds**: flag opaque files (fail-closed)
- **File classification**: inert extensions, hidden file handling
- **Finding output**: dedup, collapse same-issue across analyzers

### Python SDK (the key integration surface)

```python
from skill_scanner import SkillScanner
from skill_scanner.core.scan_policy import ScanPolicy

policy = ScanPolicy.from_preset("balanced")
scanner = SkillScanner(policy=policy)  # default: static + bytecode + pipeline
result = scanner.scan_skill("/path/to/skill")

result.is_safe           # bool: no CRITICAL/HIGH findings
result.max_severity      # Severity enum
result.findings          # list[Finding]
result.analyzability_score  # float (0-100%)
result.to_dict()         # JSON-serializable dict
```

### Key data models

```python
@dataclass
class Finding:
    id: str                    # unique finding ID
    rule_id: str               # rule that triggered (e.g., "CMD_INJECTION_SUBPROCESS")
    category: ThreatCategory   # e.g., ThreatCategory.COMMAND_INJECTION
    severity: Severity         # CRITICAL/HIGH/MEDIUM/LOW/INFO/SAFE
    title: str
    description: str
    file_path: str | None
    line_number: int | None
    snippet: str | None
    remediation: str | None
    analyzer: str | None       # "static", "behavioral", "llm", etc.
    metadata: dict

@dataclass
class ScanResult:
    skill_name: str
    skill_directory: str
    findings: list[Finding]
    scan_duration_seconds: float
    analyzers_used: list[str]
    analyzability_score: float | None
    analyzability_details: dict | None
    scan_metadata: dict | None
```

### Input requirement: directory path

skill-scanner's `SkillLoader` requires a **directory path** on disk. It walks the filesystem, reads files, and uses `magika` for ML-based file type detection. This differs from dhub's in-memory approach.

**Implication**: We need to extract the zip to a temp directory before scanning.

---

## Part 3: Integration Design

### Approach: Adapter pattern

Create a bridge module that adapts between dhub's in-memory zip-based pipeline and skill-scanner's directory-based scanner.

### Architecture

```
                    ┌─────────────────────────────────────────┐
                    │         registry_service.py              │
                    │     run_gauntlet_pipeline()              │
                    ├─────────────────────────────────────────┤
                    │                                         │
                    │  1. run_static_checks()  [existing]     │
                    │     ↓ GauntletReport (grade A/B/C/F)    │
                    │                                         │
                    │  2. run_skill_scanner()  [NEW bridge]   │
                    │     ↓ ScannerReport (findings, is_safe) │
                    │                                         │
                    │  3. Merge results → final grade         │
                    │                                         │
                    └─────────────────────────────────────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │   skill_scanner_bridge.py [NEW]  │
                    ├─────────────────────────────────┤
                    │                                  │
                    │  1. Extract zip → temp dir       │
                    │  2. Configure ScanPolicy         │
                    │  3. SkillScanner.scan_skill()    │
                    │  4. Map ScanResult → dhub format │
                    │  5. Cleanup temp dir             │
                    │                                  │
                    └──────────────────────────────────┘
```

### Phase 1: Run alongside (shadow mode)

**Goal**: Get signal from skill-scanner without changing publish behavior. Store results for analysis.

**Changes**:
1. Add `cisco-ai-skill-scanner` to `server/pyproject.toml`
2. Create `decision_hub/domain/skill_scanner_bridge.py`:
   - `scan_skill_zip(zip_bytes, skill_name, description) -> dict` — extracts zip to temp dir, runs scanner, returns serializable results
3. In `registry_service.run_gauntlet_pipeline()`, call bridge after existing checks
4. Store scanner findings alongside existing `llm_reasoning` in audit log (or new JSONB column)
5. Update Modal image to include the new dependency

**Risk**: None to publish behavior. Only additive.

### Phase 2: Replace redundant checks

**Goal**: Let skill-scanner handle pattern detection. Keep dhub's Gemini judge as a second opinion.

**Remove from `gauntlet.py`**:
- `_SUSPICIOUS_PATTERNS` + `check_safety_scan()` → replaced by skill-scanner static analyzer
- `_CREDENTIAL_PATTERNS` + `check_embedded_credentials()` → replaced by skill-scanner `hardcoded_secrets` rules
- `_PROMPT_INJECTION_PATTERNS` + `check_prompt_safety()` → replaced by skill-scanner `prompt_injection` rules

**Keep**:
- `check_manifest_schema()` — not covered by skill-scanner (dhub has stricter manifest requirements)
- `check_dependency_audit()` — skill-scanner doesn't check lockfiles
- `detect_elevated_permissions()` — used for B-grade logic (A→B escalation)
- `compute_grade()` — adapted to use scanner severity levels

**Grade mapping**:
```
CRITICAL or HIGH finding  →  F (fail)
MEDIUM finding            →  C (warn)
No findings + elevated    →  B
No findings               →  A
```

### Phase 3: Enable LLM and meta-analyzer

Use skill-scanner's built-in LLM analyzer (supports Gemini via `litellm`) for semantic analysis, and meta-analyzer for false positive reduction. This would replace the custom Gemini judge callbacks.

### Phase 4: Frontend integration

Expose per-finding scanner results in the skill detail page: severity badge, threat category, file location, code snippet, remediation text, analyzability score.

---

## Part 4: Technical Considerations

### Dependency weight

skill-scanner adds significant dependencies:

| Package | Size | Purpose |
|---------|------|---------|
| `yara-x` | ~15 MB wheel | Rust-based YARA engine |
| `magika` | ~50 MB model | ML file type detection |
| `litellm` | ~10 MB | LLM proxy (multi-provider) |
| `python-frontmatter` | <1 MB | SKILL.md parsing |
| `confusable-homoglyphs` | ~2 MB | Unicode attack detection |
| `oletools` | ~5 MB | Office document malware |
| `pdfid` | <1 MB | PDF structure analysis |
| `anthropic`, `openai` | ~5 MB each | LLM clients |

**Total**: ~90-100 MB additional in the Modal container image.

**Mitigation**:
- Install without `[all]` extras (skip Bedrock/Vertex/Azure — not needed)
- skill-scanner lazy-loads via `__getattr__` — import cost is minimal until first scan
- Profile Modal cold-start impact (currently ~30-60s; may add ~5-10s)

### YARA binary dependency

`yara-x` ships pre-built wheels for Linux x86_64 + Python 3.10-3.13. Modal uses Linux x86_64, so pip install should work. Verify during Modal image build.

### Disk I/O for scanning

skill-scanner requires extracting the zip to a temp directory:

```python
import tempfile, shutil, zipfile, io

def scan_skill_zip(zip_bytes: bytes) -> ScanResult:
    with tempfile.TemporaryDirectory(prefix="skill_scan_") as tmp:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(tmp)
        skill_dir = _find_skill_dir(tmp)  # locate SKILL.md
        scanner = SkillScanner(policy=ScanPolicy.from_preset("balanced"))
        return scanner.scan_skill(skill_dir)
```

Modal containers have writable `/tmp`. This is fine for ephemeral scan artifacts.

### Scan policy configuration

Start with `ScanPolicy.from_preset("balanced")`. Over time, create a custom `dhub_scan_policy.yaml` stored in the server package to tune:
- Disabled rules for false positives specific to the SKILL.md ecosystem
- Severity overrides for rules that are too noisy at default levels
- Analyzability thresholds (what % of files must be inspectable)

### DB schema for scanner results

**Option A**: Store in existing `llm_reasoning` JSONB column (no migration needed)
```json
{
  "scanner_result": {
    "is_safe": true,
    "max_severity": "LOW",
    "findings_count": 2,
    "analyzers_used": ["static_analyzer", "behavioral_analyzer"],
    "analyzability_score": 95.0,
    "findings": [...]
  }
}
```

**Option B**: New `scanner_findings JSONB` column on `audit_log` table (requires migration, cleaner)

Recommendation: Start with Option A for Phase 1 (zero schema changes), migrate to Option B when the feature is proven.

### Performance

| Operation | Time |
|-----------|------|
| Extract zip to temp dir | <100ms |
| skill-scanner core analyzers (static + bytecode + pipeline) | <500ms |
| skill-scanner behavioral analyzer | 200ms-1s |
| skill-scanner LLM analyzer (if enabled) | 2-5s |
| Current gauntlet with Gemini | 3-10s |

Running both in parallel adds <1s wall time (scanner finishes before Gemini). In Phase 2 (replacement), total scan time would be comparable or faster.

---

## Part 5: Files to Modify

| File | Change | Phase |
|------|--------|-------|
| `server/pyproject.toml` | Add `cisco-ai-skill-scanner` dependency | 1 |
| `server/src/decision_hub/domain/skill_scanner_bridge.py` | **New**: adapter module | 1 |
| `server/src/decision_hub/api/registry_service.py` | Call bridge in `run_gauntlet_pipeline()` | 1 |
| `server/modal_app.py` | Add skill-scanner to Modal image deps | 1 |
| `server/tests/test_skill_scanner_bridge.py` | **New**: unit tests for bridge | 1 |
| `server/src/decision_hub/domain/gauntlet.py` | Remove redundant checks | 2 |
| `server/src/decision_hub/models.py` | Optional: scanner result types | 2 |
| `server/migrations/YYYYMMDD_HHMMSS_add_scanner_findings.sql` | Optional: new JSONB column | 2 |

---

## Part 6: Open Questions

1. **Replace or augment?** Running both gives a safety net during rollout. Replacement is cleaner long-term. Recommend: Phase 1 = alongside, Phase 2 = replace overlapping checks.

2. **Which analyzers to enable?** Core (static + bytecode + pipeline) + behavioral is the best cost/benefit. LLM/meta-analyzer are optional since we already have Gemini.

3. **Custom policy file?** Start with `balanced` preset. Create a custom policy after observing false positive rates on the existing skill corpus.

4. **Modal image size?** Measure cold-start impact. The ~100MB additional deps may add 5-10s to cold starts. Acceptable given skills are scanned infrequently.

5. **License compatibility?** skill-scanner is Apache 2.0, same as would be compatible with dhub's license.

6. **Evals corpus?** skill-scanner ships with eval skills (safe + malicious) in `evals/skills/`. These could be used to validate the integration against known threats.
