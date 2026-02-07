End-to-end test of publishing a skill **with evals** on the **dev** environment. Run each step sequentially — stop and report if any step fails.

All CLI commands use: `DHUB_ENV=dev uv run --package dhub-cli dhub <command>`

## Prerequisites

1. **DB migration**: Before publishing, ensure the dev database has all columns:
   ```bash
   cd server && DHUB_ENV=dev uv run --package decision-hub-server python -c "
   from decision_hub.settings import create_settings
   from decision_hub.infra.database import create_engine, metadata
   settings = create_settings('dev')
   engine = create_engine(settings.database_url)
   metadata.create_all(engine)
   "
   ```

2. **Deploy server**: Deploy the latest server code to dev Modal:
   ```bash
   cd server && DHUB_ENV=dev modal deploy modal_app.py
   ```

## Step 1: Create the test skill

Create all files under `<scratchpad>/bayesian-ab-test/`.

### `SKILL.md`

```markdown
---
name: bayesian-ab-test
description: "Bayesian A/B testing skill using PyMC for hypothesis testing on log-normally distributed data"
runtime:
  language: python
  entrypoint: run_ab_test.py
evals:
  agent: claude
  judge_model: claude-sonnet-4-5-20250929
---

# Bayesian A/B Test

You are a statistical analysis assistant that performs Bayesian A/B testing.

When asked to run the A/B test, execute the `run_ab_test.py` script and present the results clearly.

## Instructions

1. Run `python run_ab_test.py` to generate the dataset and perform the analysis.
2. Present the output verbatim, ensuring all sections are included:
   - Hypotheses (H0 and H1)
   - Generated data summary
   - Sampling diagnostics (convergence, R-hat, ESS)
   - Posterior summary and credible intervals
   - Conclusion about the null hypothesis
3. Do NOT modify the script or its output.
```

### `pyproject.toml`

**CRITICAL**: `requires-python` MUST be `>=3.11` (not `>=3.10`) because PyMC 5.27.1 requires Python 3.11+. If set to `>=3.10`, `uv sync` will fail in the sandbox with a resolution error. Do NOT include a `[build-system]` section — it causes `uv sync` to attempt an editable install which fails.

```toml
[project]
name = "bayesian-ab-test"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "pymc==5.27.1",
    "arviz>=0.18.0",
    "numpy>=1.24",
]
```

### `run_ab_test.py`

A Python script that:
- Generates log-normally distributed data for two groups (20 samples each, different log-space means e.g. 1.0 and 1.5, shared sigma 0.5)
- Prints null (H0: mu_a = mu_b) and alternative (H1: mu_a != mu_b) hypotheses
- Prints data summary statistics
- Builds a PyMC model with Normal priors for log-space means, HalfNormal for sigma, and a Deterministic delta = mu_b - mu_a
- Samples with `pm.sample(draws=2000, tune=1000, chains=2, cores=1, random_seed=42, progressbar=False)`
- Prints convergence diagnostics (R-hat, ESS) via `az.summary()`
- Prints posterior summary, 94% HDI, and conclusion (reject/fail to reject H0 based on whether HDI excludes zero)

### `evals/hypotheses-stated.yaml`

```yaml
name: hypotheses-stated
description: "Verify that the agent output clearly states both the null and alternative hypotheses."
prompt: "Run the A/B test and report the results."
judge_criteria: |
  PASS if ALL of the following are true:
    - The output explicitly states a null hypothesis (H0) that the group means are equal (e.g. mu_a = mu_b).
    - The output explicitly states an alternative hypothesis (H1) that the group means differ (e.g. mu_a != mu_b).
    - The hypotheses are stated BEFORE the test results or conclusion section.
  FAIL if any hypothesis is missing, vague, or stated only implicitly.
```

### `evals/convergence-diagnostics.yaml`

```yaml
name: convergence-diagnostics
description: "Verify that MCMC sampling converges and diagnostics are reported."
prompt: "Run the A/B test and report the results."
judge_criteria: |
  PASS if ALL of the following are true:
    - The output includes R-hat values (or equivalent convergence metric).
    - The output includes effective sample size (ESS) or equivalent.
    - All R-hat values are below 1.05 (or explicitly stated as passing).
    - The output contains a clear conclusion that either rejects or fails to reject the null hypothesis.
    - No Python errors, tracebacks, or warnings appear in the output.
  FAIL if:
    - Convergence diagnostics are missing.
    - R-hat values indicate non-convergence (> 1.05).
    - The output contains Python errors or tracebacks.
    - There is no conclusion about the null hypothesis.
```

## Step 2: Publish the skill

```bash
DHUB_ENV=dev uv run --package dhub-cli dhub publish lfiaschi/bayesian-ab-test <scratchpad>/bayesian-ab-test
```

Expected: `Published: lfiaschi/bayesian-ab-test@<version> (Grade A)` followed by `Agent evaluation running in background...`

If you get a **500 error**, check:
- Missing DB columns → run the migration in Prerequisites
- Version conflict → the `latest-version` API still works, retry the publish

## Step 3: Poll for eval results

The eval pipeline takes **3–6 minutes** (sandbox spin-up + `uv sync` for PyMC + MCMC sampling + LLM judge). Poll the eval-report endpoint:

```bash
curl -s "https://lfiaschi--api-dev.modal.run/v1/skills/lfiaschi/bayesian-ab-test/eval-report?semver=<version>" | python3 -m json.tool
```

- Returns `null` while evals are still running.
- Wait **5 minutes** on the first poll, then poll every **90 seconds**.
- Do NOT poll more than 6 times — if still null after ~12 minutes, check Modal logs:
  ```bash
  perl -e 'alarm 15; exec @ARGV' modal app logs decision-hub-dev 2>&1 | tail -60
  ```

## Step 4: Report results

Once the eval report is returned, report:

| Field | Expected |
|-------|----------|
| `status` | `completed` |
| `passed` | `2` |
| `total` | `2` |
| `case_results[0].verdict` | `pass` |
| `case_results[1].verdict` | `pass` |

If any case has `verdict: fail`, check the `agent_output` field — common failures:
- **"packages not installed"** or **"externally managed environment"** → `uv sync` failed in sandbox. Check `requires-python` is `>=3.11` and there's no `[build-system]` section in pyproject.toml.
- **No hypotheses / no convergence info** → Agent didn't find or run the script. Check Modal logs for sandbox setup errors.

## Known pitfalls (from previous runs)

1. **`requires-python = ">=3.10"` breaks `uv sync`**: PyMC 5.27.1 needs `>=3.11`. The sandbox Python is 3.11.2, but uv resolves for all declared versions including 3.10, causing a resolution failure.
2. **No `[build-system]` in pyproject.toml**: Including it makes uv attempt an editable install with hatchling, which fails because the skill dir isn't a Python package.
3. **DB migration needed after merging new features**: If the skills table schema changed (e.g. `download_count` column), run `metadata.create_all(engine)` before publishing.
4. **Modal cold starts**: The first request after deploy can take 30–60s. The publish endpoint uses `timeout=60` internally.
5. **Eval sandboxes are independent**: Each eval case gets its own sandbox. One may succeed while another fails due to transient issues. A re-publish triggers a fresh eval run.
