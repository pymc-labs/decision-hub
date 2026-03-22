# decision-agent-lite

Docker-free fork of [decision-agent](https://github.com/pymc-labs/decision-agent-placeholder). Runs coding agents with domain-specific decision packs — without Docker.

## Why this fork

The original `dlab` runs agents inside Docker containers for reproducibility. This fork trades Docker isolation for simplicity: it uses Python venvs for dependency management and runs the agent directly on the host. Good for prototyping new decision packs, local development, and environments where Docker isn't available.

## How it works

Same decision pack concept, simpler execution:

```
my-dpack/
  config.yaml           # Name, model, dependencies
  agents/
    orchestrator.md     # Main agent system prompt
    modeler.md          # Sub-agent prompts
  skills/               # Domain knowledge (markdown)
  tools/                # Custom tools
  parallel_agents/      # Fan-out configs (yaml)
  requirements.txt      # Python dependencies (replaces Dockerfile)
```

Key differences from `dlab`:
- **No Docker** — uses `uv`/`pip` + venv instead of frozen containers
- **No opencode** — uses Claude Code as the agent runtime
- **Flat structure** — no `docker/` or `opencode/` nesting
- **`requirements.txt`** replaces `Dockerfile` for environment setup

## Install

```bash
pip install -e spikes/decision-agent-lite
```

## Quick start

```bash
# Run a decision pack
dlab-lite --dpack decision-packs/timeseries-forecasting \
          --data ./sales_data.csv \
          --prompt "Build a 12-week demand forecast with uncertainty intervals"

# Create a new decision pack
dlab-lite create-dpack my-new-pack
```

## Decision packs included

### `timeseries-forecasting`
Time series forecasting with model selection, diagnostics, and uncertainty quantification.
Supports: ARIMA/SARIMAX, Prophet-style, Bayesian structural time series, ensemble methods.

### `oil-procurement`
Bayesian procurement strategy under geopolitical uncertainty.
Monte Carlo simulation with jump-diffusion models, optimal hedge ratio via expected utility.
