# SKILL.md Format Specification

Complete reference for the SKILL.md file format. Standard fields first, then Decision Hub extensions (runtime, evals).

## File Structure

A SKILL.md file has two parts:

1. **YAML frontmatter** between `---` delimiters — structured metadata
2. **Markdown body** — the agent system prompt

```
---
<frontmatter fields>
---
<body: agent system prompt in markdown>
```

## Required Fields

| Field | Type | Constraints | Description |
|-------|------|------------|-------------|
| `name` | string | 1-64 chars, regex `^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$` | Unique skill identifier. Lowercase alphanumeric + hyphens, no leading/trailing hyphens. Must match the directory name. |
| `description` | string | 1-1024 chars | What the skill does and when to use it. This is always in context — it determines when the skill triggers. Write for an LLM router, not a human. |

## Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `license` | string | `null` | SPDX license identifier (e.g. `Apache-2.0`, `MIT`) |
| `compatibility` | string | `null` | Requirements or constraints (e.g. "Requires internet access") |
| `metadata` | mapping | `null` | Key-value pairs (e.g. `author: my-org`, `version: 1.0`) |
| `allowed_tools` | string | `null` | Tool access restrictions for the agent |

## Runtime Block (Decision Hub Extension)

Declares what the skill needs to execute code. Presence of this block signals that the skill has executable components.

```yaml
runtime:
  language: python           # Required. Only "python" supported.
  entrypoint: scripts/main.py  # Required. Path to main script, relative to skill root.
  version_hint: ">=3.11"    # Optional. Python version constraint.
  env:                       # Optional. Environment variable names the skill needs.
    - OPENAI_API_KEY
    - MY_API_SECRET
  capabilities:              # Optional. System capabilities needed.
    - network
  dependencies:              # Optional. Package dependencies.
    system: []               # OS-level packages
    package_manager: uv      # Package manager (uv, pip)
    packages:                # Direct package specs
      - pandas>=2.0
      - scikit-learn
    lockfile: uv.lock        # Path to lockfile, relative to skill root
  repair_strategy: attempt_install  # Optional. Default: "attempt_install".
                                    # Options: "strict", "attempt_install", "isolation_required"
```

### Runtime Field Details

| Field | Type | Required | Default | Constraints |
|-------|------|----------|---------|-------------|
| `language` | string | yes | — | Must be `"python"` |
| `entrypoint` | string | yes | — | File must exist at the specified path |
| `version_hint` | string | no | `null` | Version constraint string |
| `env` | list[string] | no | `[]` | Items should be `UPPER_SNAKE_CASE` |
| `capabilities` | list[string] | no | `[]` | e.g. `internet_outbound`, `filesystem_write`, `shell_exec` |
| `dependencies` | mapping | no | `null` | See DependencySpec below |
| `repair_strategy` | string | no | `"attempt_install"` | `"strict"`, `"attempt_install"`, or `"isolation_required"` |

### DependencySpec

| Field | Type | Required | Default |
|-------|------|----------|---------|
| `system` | list[string] | no | `[]` |
| `package_manager` | string | no | `""` |
| `packages` | list[string] | no | `[]` |
| `lockfile` | string | no | `null` |

## Evals Block (Decision Hub Extension)

Configures automated evaluation for the skill. Eval cases are defined in separate YAML files under `evals/`.

```yaml
evals:
  agent: claude                        # Required. Agent that runs the skill.
  judge_model: claude-sonnet-4-5-20250929  # Required. Model that judges results.
```

### Evals Field Details

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `agent` | string | yes | Agent identifier: `claude`, `codex`, `gemini` |
| `judge_model` | string | yes | Model ID for the LLM judge (e.g. `claude-sonnet-4-5-20250929`, `gpt-4o`) |

## Eval Case YAML Format

Each file in `evals/*.yaml` defines one test case.

```yaml
# evals/my-test-case.yaml
name: my-test-case
description: Verifies the agent handles edge case X correctly
prompt: |
  Analyze the data in evals/data/sample.csv and produce a summary report.
judge_criteria: |
  ## Required Behaviors
  - Loads the CSV without errors
  - Produces a summary with row count and column names

  ## Forbidden Behaviors
  - Hallucinates data not present in the file
  - Skips error handling for malformed rows

  ## Scoring
  PASS if all Required Behaviors are present AND no Forbidden Behaviors appear.
```

### Eval Case Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Unique identifier for this eval case |
| `description` | string | no | Human-readable description of what this tests |
| `prompt` | string | yes | The user message sent to the agent |
| `judge_criteria` | string | yes | Free-text criteria interpreted by the LLM judge. Can range from a single sentence to structured building blocks. |

### Judge Evaluation

The judge receives the eval case name, the `judge_criteria`, and the agent's output (truncated to 10,000 chars). It returns a verdict (`pass`, `fail`, or `error`) with reasoning.

The three-stage eval pipeline:
1. **Sandbox** — execute the skill in an isolated environment
2. **Agent** — check exit code (non-zero = error, skip judge)
3. **Judge** — LLM evaluates agent output against criteria

## Validation Rules

| Check | Severity | Description |
|-------|----------|-------------|
| SKILL.md exists | error | File must be present in skill root |
| Valid YAML frontmatter | error | Must have `---` open and close delimiters with valid YAML |
| Body non-empty | error | Markdown body after frontmatter must have content |
| `name` present and valid | error | Matches `^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$` |
| `name` matches directory | error | Skill name must equal the containing directory name |
| `description` present, 1-1024 chars | error | Required, length-bounded |
| No TODO/placeholder in name/description | error | Catches forgotten scaffolding text |
| `runtime.language` is `"python"` | error | Only supported language |
| `runtime.entrypoint` exists | error | File must exist at declared path |
| `runtime.env` items look like env vars | warning | Expected `UPPER_SNAKE_CASE` |
| `evals.agent` present | error | Required when evals block exists |
| `evals.judge_model` present | error | Required when evals block exists |
| At least one `evals/*.yaml` exists | warning | Evals block without cases is incomplete |
| Eval YAML has name, prompt, judge_criteria | error | Required fields per case |
| Eval names are unique | error | No duplicate names across cases |
| Description < 20 chars | warning | Likely too short to be useful |
| Body < 100 chars | warning | Likely too short to be a useful system prompt |

## Complete Annotated Example

```yaml
---
name: data-analyzer
description: Analyze datasets using statistical methods. Handles exploratory data analysis, hypothesis testing, and causal inference. Use when asked to analyze CSV/Excel data, run A/B test analysis, or identify patterns in tabular data.
license: MIT
metadata:
  author: analytics-team
runtime:
  language: python
  entrypoint: scripts/analyze.py
  version_hint: ">=3.11"
  env:
    - OPENAI_API_KEY
  capabilities:
    - network
  dependencies:
    package_manager: uv
    packages:
      - pandas>=2.0
      - scipy
      - statsmodels
    lockfile: uv.lock
  repair_strategy: attempt_install
evals:
  agent: claude
  judge_model: claude-sonnet-4-5-20250929
---
# Data Analyzer

Analyze tabular datasets with rigorous statistical methods.

## Workflow

1. Load the dataset and inspect schema, types, missing values.
2. Select appropriate statistical methods based on data characteristics.
3. Run analysis and produce a report with visualizations.
4. Verify assumptions (normality, independence) before parametric tests.

## Important Constraints

- Never fabricate data points not present in the source.
- Always check distributional assumptions before selecting tests.
- Report confidence intervals alongside p-values.
- Use non-parametric alternatives when assumptions are violated.

## Output Format

Produce a markdown report with:
- Executive summary (2-3 sentences)
- Methodology section
- Results with tables and inline statistics
- Limitations and caveats
```

### Corresponding Eval Case

```yaml
# evals/nonparametric-fallback.yaml
name: nonparametric-fallback
description: Verifies the agent falls back to non-parametric tests for skewed data
prompt: |
  Analyze the dataset at evals/data/skewed_outcomes.csv.
  Columns: treatment (0/1), outcome (continuous, heavily right-skewed).
  Determine if treatment has a significant effect on outcome.
judge_criteria: |
  ## Required Behaviors
  - Checks data distribution before selecting a statistical test
  - Uses a non-parametric test (Mann-Whitney U, Wilcoxon, bootstrap, or permutation test)
  - Reports a test statistic and p-value

  ## Forbidden Behaviors
  - Applies t-test or ANOVA without verifying normality first
  - Claims normality when the data is heavily skewed

  ## Examples
  Good: "The Shapiro-Wilk test (p=0.003) rejects normality, so using Mann-Whitney U..."
  Bad: "Running a two-sample t-test gives p=0.04, so the treatment works."

  ## Scoring
  PASS if all Required Behaviors present AND no Forbidden Behaviors appear.
```
