---
name: dhub-skill-creator
description: Guide for creating effective skills for Claude Code agents. Covers skill design, implementation, validation, packaging, and optionally runtime environments and automated evaluations for Decision Hub publishing. Use when users want to create, improve, or package a skill.
---
# Decision Hub Skill Creator

Create modular skill packages (SKILL.md + optional resources) that turn Claude into a specialist. This skill guides the full lifecycle: define the domain, design the architecture, build and validate the skill, and package it for distribution.

For skills intended for Decision Hub, the workflow naturally extends into defining runtime environments and writing evaluation criteria — not as a separate mode, but as a natural consequence of what the skill needs.

## Anatomy of an Effective Skill

### What a Skill Contains

Progressive disclosure — each layer loads only when needed:

1. **Metadata** (always in context): `name` + `description` in frontmatter. Determines when the skill activates.
2. **SKILL.md body** (when triggered): The agent system prompt. Core procedures, workflow, constraints.
3. **Bundled resources** (as needed):
   - `scripts/` — deterministic code the agent executes via Bash
   - `references/` — domain knowledge the agent reads on demand
   - `assets/` — templates, sample data, output formats
   - `agents/` — subagent system prompts for delegation

### Patterns That Make Skills Effective

| Pattern | Why It Works | Example |
|---------|-------------|---------|
| Architecture diagram up front | Agent grasps the big picture before details | ASCII flow showing phase transitions |
| Review gates | Prevents runaway execution, gives user control points | "HARD STOP — present outline, wait for approval" |
| Subagent delegation | Separates concerns, each agent does one thing well | Actor-critic loop: generate → critique → revise |
| Anti-patterns / blacklists | Tells agent what NOT to do — as important as what to do | List of cliches to never use |
| Quality checklists | Actionable verification before output | Design system checklist with checkboxes |
| Sensible defaults | Reduces friction — ask only what's needed | Default assumptions table at skill start |
| Concrete examples | Shows expected behavior, not just rules | Good/bad output snippets inline |

### What to Avoid

- Generic TODO templates the agent fills with boilerplate
- Excessive placeholder files that create clutter to delete
- Vague descriptions like "A helpful skill" — triggers for wrong contexts
- Instructions written for humans instead of agents
- Duplicating content between SKILL.md and references
- Overly long SKILL.md — move detail to `references/`

## Skill Creation Workflow

Four phases. Not rigid steps — they overlap and the depth of each depends on the skill's complexity.

### Phase 1 — Define the Domain

Understand what the skill does before building anything. Ask focused questions:

- **What specific tasks does this skill handle?** Not "data analysis" but "causal inference for A/B tests, lift analysis, treatment effect estimation."
- **What triggers should activate this skill?** Maps directly to the `description` field. Think about what a user would say.
- **What does the agent need to know that it doesn't already know?** This is the test for whether content belongs in the skill. If Claude already knows it, don't include it.

Ask 2-3 focused questions. Never more than 5. Gather enough to make design decisions, then move on.

### Phase 2 — Design the Architecture

Choose the structural pattern and identify resources. Read `references/skill_patterns.md` for detailed patterns.

**Choose a structural pattern:**
- **Workflow-based** — multi-step processes with phases and review gates
- **Task-based** — focused input/output with processing rules
- **Agent-delegation** — multiple subagents, each handling one concern
- **Reference-based** — augmenting with domain knowledge the agent lacks

**Identify bundled resources:**
- What scripts need to exist in `scripts/`?
- What reference material goes in `references/`?
- Does the skill need subagents in `agents/`?
- Are there template files for `assets/`?

**Determine if the skill needs runtime or evals blocks.** These are about the skill's nature — whether it has executable code or should be automatically testable — not about where the skill will be published.

- **Runtime block**: Ask "Does this skill include executable code or dependencies?" If yes, ask what language/packages it needs and any required API keys, then define the `runtime` block in frontmatter. See `references/format_spec.md` for field details.
- **Evals block**: Ask "Should this skill be automatically testable?" If yes, ask "What does 'correct' look like? Describe a scenario where it should pass and one where it should fail." Then guide eval case authoring in Phase 3b.

### Phase 3a — Build the Skill

1. **Scaffold.** Run `scripts/init_skill.py` to create the directory:
   ```
   python internal-skills/dhub-skill-creator/scripts/init_skill.py <name> --path <dir> [--with-runtime] [--with-evals] [--description "..."]
   ```

2. **Write the SKILL.md body.** Follow the writing guidelines below. The body is the agent system prompt — procedural knowledge the agent cannot infer on its own.

3. **Build resources.** Create scripts, references, assets, agents as designed. For runtime skills, ensure the entrypoint exists and dependencies are declared.

4. **Validate early.** Run `scripts/validate_skill.py` during development, not just at the end.

### Phase 3b — Author Evaluation Cases

When the skill has an `evals` block, help the user construct eval cases through a structured interview.

**Step 1 — Identify what to test.** Each eval case tests one specific behavior.
- "What's the most important thing this skill must get right?"
- "What's the most common way it could fail?"

**Step 2 — Write the eval prompt.** A realistic user message — what a real person would say to trigger this skill. Keep it focused. Include test data in `evals/data/` if needed.

**Step 3 — Compose judge criteria.** The `judge_criteria` field is free-text interpreted by an LLM judge. Build it from structured blocks — pick whichever are relevant:

**Required Behaviors** — things the agent MUST do:
```
## Required Behaviors
- Checks data distribution before selecting a statistical test
- Reports confidence intervals, not just p-values
```

**Forbidden Behaviors** — things that cause automatic failure:
```
## Forbidden Behaviors
- Applies parametric tests without verifying normality
- Hallucinates data that wasn't in the input file
```

**Expected Output Contains** — specific patterns or concepts:
```
## Expected Output Contains
- A test statistic and p-value
- An interpretation in plain language
```

**Calibration Examples** — good/bad snippets so the judge knows what "right" looks like:
```
## Examples
Good: "Shapiro-Wilk test (p=0.003) rejects normality, using Mann-Whitney U..."
Bad: "Running a t-test gives p=0.04, so the treatment works."
```

**Threshold** — how to combine criteria into pass/fail:
```
## Scoring
PASS if all Required Behaviors present AND no Forbidden Behaviors appear.
```

Interview the user to populate these blocks:
- "Describe what a correct output looks like" → Required Behaviors + Expected Output
- "What would a wrong output look like?" → Forbidden Behaviors + bad Example
- "Can you show a snippet of ideal output?" → good Example

For simple cases, a single sentence works: `"PASS if the agent creates a valid CSV file with headers matching the schema. FAIL otherwise."`

**Step 4 — Assemble the eval YAML.** Create `evals/<case-name>.yaml` with `name`, `description`, `prompt`, and `judge_criteria` fields. See `references/format_spec.md` for the complete spec and `references/skill_patterns.md` for the eval criteria authoring guide.

## Writing Guidelines

- **Write for an AI agent, not a human.** Focus on procedural knowledge the agent cannot infer from its training.
- **Imperative form.** "Parse the input" not "You should parse the input."
- **Be specific about what NOT to do.** Agents tend toward generic outputs unless constrained. Anti-pattern lists and blacklists are highly effective.
- **Include concrete examples.** Show expected input/output pairs, good/bad snippets. Examples outperform abstract rules.
- **Keep SKILL.md under 5000 words.** Move detailed specs, lookup tables, and large examples to `references/`.
- **Every instruction must be actionable.** If the agent cannot act on a sentence, delete it. No throat-clearing, no meta-commentary.
- **Use tables for structured data.** Default assumptions, field specs, command references — tables are faster to parse than prose.
- **One section, one concern.** Don't mix workflow steps with quality criteria. Separate them.

## Validate, Package, Iterate

### Validate

Run validation during development to catch issues early:

```
python internal-skills/dhub-skill-creator/scripts/validate_skill.py <skill-dir>
python internal-skills/dhub-skill-creator/scripts/validate_skill.py <skill-dir> --strict
```

Fix all errors before packaging. Address warnings to improve quality.

### Package

Create a distributable zip (runs validation first):

```
python internal-skills/dhub-skill-creator/scripts/package_skill.py <skill-dir> [--output-dir <dir>]
```

### Iterate

Test the skill by using it on real tasks. Notice gaps, iterate on the SKILL.md and resources. Skills improve through use, not through planning.

### Publish

After validation and packaging, ask the user: "Do you want to publish this skill to Decision Hub?" If yes:

```
dhub publish --org <org> --name <skill>
```

Run from the skill directory. The server validates the manifest, runs safety checks, and optionally triggers eval runs.

## Quick Reference

### Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `init_skill.py` | Scaffold a new skill | `python scripts/init_skill.py <name> --path <dir> [--with-runtime] [--with-evals] [--description "..."]` |
| `validate_skill.py` | Validate a skill directory | `python scripts/validate_skill.py <skill-dir> [--strict]` |
| `package_skill.py` | Validate + zip for distribution | `python scripts/package_skill.py <skill-dir> [--output-dir <dir>]` |

### Frontmatter Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | 1-64 chars, `^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$` |
| `description` | yes | 1-1024 chars, what the skill does + when to trigger |
| `license` | no | SPDX identifier |
| `compatibility` | no | Requirements or constraints |
| `metadata` | no | Key-value pairs |
| `allowed_tools` | no | Tool access restrictions |
| `runtime` | no | Executable code configuration (see `references/format_spec.md`) |
| `evals` | no | Automated evaluation configuration (see `references/format_spec.md`) |

### Validation Checks Summary

- 10 error-level checks: SKILL.md exists, valid frontmatter, non-empty body, valid name, name matches dir, valid description, no placeholders, runtime language/entrypoint, evals agent/judge_model, eval YAML fields, unique eval names
- 5 warning-level checks: short description, short body, env var naming, missing eval files, `--strict` promotes all to errors

## Troubleshooting

**"SKILL.md not found"** — Ensure you point to the skill directory, not the SKILL.md file itself.

**"name does not match directory name"** — The `name` field in frontmatter must exactly match the containing directory name. Rename either one.

**"Frontmatter is not valid YAML"** — Check for unquoted colons in field values. Wrap the description in quotes if it contains colons: `description: "My skill: does things"`.

**"entrypoint does not exist"** — The file at `runtime.entrypoint` must exist relative to the skill root. Create the file or fix the path.

**"No evals/*.yaml files found"** — Either add eval case YAML files to the `evals/` directory, or remove the `evals` block from frontmatter if evals aren't needed yet.

**Validation passes but skill doesn't trigger** — The `description` may be too vague. Make it specific with concrete task types and "Use when..." phrasing.

**Zip excludes needed files** — The packager excludes `__pycache__/`, `*.pyc`, `.DS_Store`, `.git/`, `*.egg-info/`, `.env*`. If a needed file matches these patterns, rename it.
