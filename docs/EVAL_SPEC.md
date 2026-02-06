# Decision Hub Eval & Runtime Spec

Extensions to the [agentskills.io/specification](https://agentskills.io/specification) for soft-contract runtimes and agent evaluations.

## Runtime: the Soft Contract

Skills declare their ideal execution environment as a *request for capabilities*. The harness (Modal sandbox or local machine) provides a baseline; the agent bridges the gap.

### `runtime` block

```yaml
runtime:
  language: python
  version_hint: ">=3.10"
  entrypoint: scripts/analyze.py
  env:
    - OPENAI_API_KEY
  capabilities:
    - internet_outbound
    - filesystem_write
  dependencies:
    system:
      - ffmpeg
      - libpq-dev
    package_manager: uv
    packages:
      - pandas>=2.0
      - scipy>=1.10
    lockfile: uv.lock
  repair_strategy: attempt_install
```

### Fields

| Field | Required | Description |
|-------|----------|-------------|
| `language` | yes | `"python"` (only supported language for now) |
| `entrypoint` | yes | Script path relative to skill root |
| `version_hint` | no | PEP 440 version specifier hint, e.g. `">=3.10"` |
| `env` | no | Environment variable names the skill's scripts need at execution time |
| `capabilities` | no | Abstract permissions: `internet_outbound`, `filesystem_write`, `shell_exec` |
| `dependencies.system` | no | System packages installed via `apt` |
| `dependencies.package_manager` | no | `"uv"` (default), `"pip"` |
| `dependencies.packages` | no | Python packages with version constraints |
| `dependencies.lockfile` | no | Lockfile path relative to skill root |
| `repair_strategy` | no | `"strict"` (fail), `"attempt_install"` (default), `"isolation_required"` |

### Capabilities

Declared capabilities serve two purposes:
1. The gauntlet cross-checks declared capabilities against code patterns
2. `dhub run` can warn users about permission requirements before execution

### Repair strategies

- **`strict`** -- fail immediately if dependencies are missing
- **`attempt_install`** -- try to install missing packages (default)
- **`isolation_required`** -- must run in a fresh sandbox (Modal always does this)

### Extensibility

`language` and `dependencies.package_manager` are the extension points. Future languages (e.g. `node`) add conventions without breaking the schema.

## Evals Block

Skills can declare evaluation configuration in the frontmatter:

```yaml
evals:
  agent: claude
  judge_model: claude-sonnet-4-5-20250929
```

| Field | Required | Description |
|-------|----------|-------------|
| `agent` | yes | Agent to run evals with: `claude`, `codex`, `gemini` |
| `judge_model` | yes | Anthropic model ID for the LLM judge |

## Eval Cases

Place YAML files in the `evals/` directory. Each file defines one evaluation case:

```yaml
# evals/nonparametric_test.yaml
name: uses-nonparametric-test
description: Verifies the agent uses appropriate statistical tests for non-normal data
prompt: |
  I have a dataset at evals/data/causal_data.csv with columns: treatment (0/1),
  outcome (continuous). The outcome is heavily skewed. Analyze the causal effect.
judge_criteria: |
  PASS: Agent uses non-parametric tests (Mann-Whitney U, Kruskal-Wallis, bootstrap)
  FAIL: Agent uses parametric tests (t-test, ANOVA) without checking assumptions
```

### Required fields per case

| Field | Description |
|-------|-------------|
| `name` | Unique identifier for this case |
| `description` | Human-readable description |
| `prompt` | The prompt sent to the agent |
| `judge_criteria` | PASS/FAIL criteria for the LLM judge |

### Data files

Place test data in `evals/data/`. These files are included in the skill zip and available to the agent during evaluation.

## Directory Structure

```
causal-analysis/
+-- SKILL.md
+-- uv.lock
+-- scripts/
|   +-- analyze.py
+-- evals/
    +-- nonparametric_test.yaml
    +-- handles_missing_data.yaml
    +-- data/
        +-- causal_data.csv
        +-- missing_data.csv
```

## Eval Reports

After publish, if the skill has an `evals` block, the platform:
1. Parses eval cases from the `evals/` directory in the zip
2. Spins up a Modal sandbox with the specified agent
3. Runs each eval prompt through the agent
4. An LLM judge evaluates the output against the criteria
5. Results are stored as an eval report

### Report format

Each case result includes:
- `verdict`: `"pass"`, `"fail"`, or `"error"`
- `reasoning`: Judge reasoning or error detail
- `agent_output`: Full agent stdout
- `agent_stderr`: Full agent stderr
- `exit_code`: Agent process exit code
- `duration_ms`: Wall clock time for this case
- `stage`: Which stage completed: `"sandbox"`, `"agent"`, or `"judge"`

### Self-certification disclaimer

Eval reports are **self-certified by the publisher**. The publisher's API key funds both agent execution and judging. Reports are informational transparency, not trust assertions.

## Writing Good Eval Cases

1. **One thing per case** -- test a single behavior or capability
2. **Clear PASS/FAIL criteria** -- the LLM judge needs unambiguous rules
3. **Include edge cases** -- missing data, malformed input, boundary conditions
4. **Use realistic data** -- place test datasets in `evals/data/`
5. **Keep prompts focused** -- shorter prompts give clearer signals
6. **Name descriptively** -- `uses-nonparametric-test` not `test-1`
