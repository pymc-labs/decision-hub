# Skill Design Patterns & Eval Criteria Guide

## Part 1 — Skill Design Patterns

### Structural Patterns

Choose based on what the skill does:

#### Workflow-Based
The skill guides the agent through a sequence of phases with defined transitions.

**When to use:** Multi-step processes where order matters — report generation, data pipelines, content creation with review cycles.

**Structure:**
```
Phase 1: Gather inputs → Phase 2: Process → Phase 3: Review gate → Phase 4: Output
```

**Key elements:**
- Numbered phases with explicit entry/exit criteria
- Review gates between phases (hard stops where the agent presents work and waits for approval)
- Default assumptions table to reduce friction (skip unnecessary questions)

**Example pattern (from slide-generator):**
```markdown
## Phase 2: Design

Build slides following the design system.

### Design System Checklist
- [ ] Consistent heading hierarchy
- [ ] Max 6 bullet points per slide
- [ ] Visual anchors on data slides

### HARD STOP
Present the slide outline to the user. Do not proceed to rendering until approved.
```

#### Task-Based
The skill handles a specific category of tasks with clear input/output contracts.

**When to use:** Focused utilities — code review, data transformation, file conversion, analysis.

**Structure:**
```
Input spec → Processing rules → Output spec → Quality checks
```

**Key elements:**
- Explicit input format and constraints
- Processing rules as imperative instructions
- Output format specification
- Validation criteria

#### Agent-Delegation
The skill orchestrates multiple subagents, each responsible for a distinct concern.

**When to use:** Complex tasks where quality benefits from separation of concerns — writing with editing, analysis with critique, multi-perspective evaluation.

**Structure:**
```
Coordinator → Subagent A (generate) → Subagent B (critique) → Coordinator (synthesize)
```

**Key elements:**
- `agents/` directory with one file per subagent
- Each subagent has a focused system prompt
- Coordinator manages handoffs and synthesizes outputs

**Example pattern (from humanize, actor-critic loop):**
```markdown
## Actor-Critic Loop

1. **Actor agent** generates the initial output
2. **Critic agent** evaluates against quality criteria and provides specific feedback
3. **Actor agent** revises based on critique
4. Repeat until critic approves or max 3 iterations
```

#### Reference-Based
The skill augments the agent with domain knowledge it lacks, loaded on demand.

**When to use:** Specialized domains where the agent's training data is insufficient — niche APIs, internal tools, proprietary formats.

**Structure:**
```
SKILL.md (when to reference what) → references/ (domain knowledge)
```

**Key elements:**
- SKILL.md stays concise — routing logic and procedures
- `references/` contains detailed specs, API docs, format guides
- Agent reads references on demand, not all at once

### Review Gates

Prevent runaway execution by requiring user approval at key checkpoints.

**When to use:** Any skill where the cost of going in the wrong direction is high — content creation, code generation, multi-step modifications.

**Format:**
```markdown
### REVIEW GATE: [Gate Name]

Present the following to the user and STOP:
- [Item 1 to show]
- [Item 2 to show]

Do NOT proceed until the user explicitly approves.
```

**Tips:**
- Place gates after planning/before execution, after first draft/before refinement
- Show enough context for the user to make an informed decision
- Keep the presentation concise — bullet points, not paragraphs

### Anti-Pattern Lists

Tell the agent what NOT to do. Agents tend toward generic outputs unless explicitly constrained.

**Format:**
```markdown
## Blacklist — Never Do These

- Never use the phrase "leverage" — use "use" instead
- Never start a paragraph with "In conclusion"
- Never produce bullet points when a table would be clearer
- Never assume the user wants verbose output — default to concise
```

**Why this works:** Negative constraints are as important as positive instructions. Without them, agents default to safe, generic patterns.

### Progressive Disclosure

Control what goes where based on how often the agent needs it:

| Location | Loaded | Use For |
|----------|--------|---------|
| `name` + `description` | Always in context | Trigger matching — when to activate |
| SKILL.md body | When skill triggers | Core procedures, workflow, constraints |
| `references/` | On demand via Read | Detailed specs, large examples, lookup tables |
| `scripts/` | On demand via Bash | Deterministic operations (validation, formatting, computation) |
| `assets/` | On demand | Templates, sample data, output formats |
| `agents/` | When delegating | Subagent system prompts |

**Rule of thumb:** If the agent needs it every time → SKILL.md body. If it needs it sometimes → `references/`. If it should execute it → `scripts/`.

### Writing Effective Descriptions

The `description` field determines when your skill activates. It's always in context, evaluated by an LLM router.

**Good descriptions:**
- `"Analyze datasets using statistical methods. Handles EDA, hypothesis testing, and causal inference. Use when asked to analyze CSV/Excel data or run A/B test analysis."`
- `"Generate presentation slides from content. Handles layout, design system, and speaker notes. Use when asked to create slides, decks, or presentations."`

**Bad descriptions:**
- `"A helpful data skill"` — too vague, triggers on unrelated data tasks
- `"This skill helps users"` — tells the router nothing about the domain
- `"Skill for doing things with files"` — will trigger on every file operation

**Tips:**
- Lead with the primary capability, not meta-description
- Include concrete task types (A/B tests, causal inference) — these are trigger phrases
- End with "Use when..." to explicitly define activation conditions
- Third-person perspective: describe what the skill does, not what "you" do

---

## Part 2 — Eval Criteria Authoring Guide

### The Building Blocks Approach

The `judge_criteria` field in eval cases is free-text interpreted by an LLM judge. Structure criteria using these building blocks — pick whichever are relevant.

#### Required Behaviors
Things the agent MUST do for a passing evaluation.

```yaml
judge_criteria: |
  ## Required Behaviors
  - Checks data distribution before selecting a statistical test
  - Reports confidence intervals, not just p-values
  - Handles missing values explicitly (drop, impute, or explain)
```

**Tips:**
- Each item should be independently verifiable
- Use observable actions: "checks", "reports", "creates", "validates"
- Avoid subjective criteria: "writes good code" is unjudgeable

#### Forbidden Behaviors
Things that cause automatic failure — catches the most common mistakes.

```yaml
judge_criteria: |
  ## Forbidden Behaviors
  - Applies parametric tests without verifying normality
  - Hallucinates data that wasn't in the input file
  - Uses deprecated API endpoints
```

**Tips:**
- Focus on the most common failure modes
- Each forbidden behavior should be unambiguously detectable
- Include at least one forbidden behavior per eval case

#### Expected Output Contains
Specific patterns, concepts, or structures the output must include.

```yaml
judge_criteria: |
  ## Expected Output Contains
  - A test statistic and p-value
  - An interpretation of the result in plain language
  - A file saved to the specified output path
```

#### Calibration Examples
Show the judge what "right" and "wrong" look like with concrete snippets.

```yaml
judge_criteria: |
  ## Examples
  Good: "The Shapiro-Wilk test (W=0.87, p=0.003) rejects normality at alpha=0.05, so using Mann-Whitney U for group comparison..."
  Bad: "Running a two-sample t-test gives p=0.04, so the treatment is effective."
```

**Tips:**
- Good examples show the ideal reasoning chain
- Bad examples show the specific mistake you're testing against
- Keep examples short — a sentence or two, not paragraphs

#### Threshold / Scoring
How to combine multiple criteria into a single pass/fail verdict.

```yaml
judge_criteria: |
  ## Scoring
  PASS if all Required Behaviors are present AND no Forbidden Behaviors appear.
```

Or for partial credit:
```yaml
judge_criteria: |
  ## Scoring
  PASS if at least 3 of 4 Required Behaviors present AND no Forbidden Behaviors.
```

### Composing Criteria — By Complexity

#### Simple (single sentence)
For straightforward checks:
```yaml
judge_criteria: "PASS if the agent creates a valid CSV file with headers matching the schema. FAIL otherwise."
```

#### Moderate (2-3 blocks)
For most eval cases:
```yaml
judge_criteria: |
  ## Required Behaviors
  - Loads the input CSV without errors
  - Produces a summary with row count and column statistics

  ## Forbidden Behaviors
  - Fabricates data not present in the source file

  PASS if all Required Behaviors present and no Forbidden Behaviors.
```

#### Detailed (full scorecard)
For critical behaviors:
```yaml
judge_criteria: |
  ## Required Behaviors
  - Verifies distributional assumptions before test selection
  - Uses appropriate non-parametric test for skewed data
  - Reports effect size alongside significance

  ## Forbidden Behaviors
  - Applies parametric tests to non-normal data without justification
  - Reports only p-values without effect size
  - Makes causal claims from observational data

  ## Expected Output Contains
  - A normality test result (Shapiro-Wilk, Anderson-Darling, or Q-Q plot reference)
  - A test statistic with degrees of freedom
  - A confidence interval

  ## Examples
  Good: "Shapiro-Wilk rejects normality (p=0.003), switching to Mann-Whitney U. U=1234, p=0.021, rank-biserial r=0.34 (medium effect)."
  Bad: "t(98)=2.1, p=0.04. The treatment is statistically significant."

  ## Scoring
  PASS if all Required Behaviors present, at least 2 of 3 Expected Output items present, and no Forbidden Behaviors.
```

### Eval Authoring Tips

- **One behavior per case.** Test one specific thing. "Does it handle skewed data?" is a good case. "Does it handle skewed data and missing values and outliers?" is three cases.
- **Realistic prompts.** Write eval prompts the way a real user would — natural language, not test-speak. Include enough context but don't over-specify.
- **Binary and unambiguous.** The judge needs to produce a clear pass/fail. "Output should be good" is unjudgeable. "Output must contain a p-value" is clear.
- **Include negative tests.** At least one eval case should test a forbidden behavior — what the skill must NOT do.
- **Use test data.** Place test datasets in `evals/data/`. Reference them in eval prompts with relative paths.
- **Keep criteria concise.** The judge has a 10,000 character limit on agent output. Keep criteria proportionate.

### Eval Anti-Patterns

| Anti-Pattern | Why It Fails | Fix |
|-------------|-------------|-----|
| "Output should be high quality" | Subjective, unjudgeable | Specify observable criteria |
| Testing 5 behaviors in one case | Hard to diagnose failures | Split into separate cases |
| Prompts that say "for this test..." | Unrealistic, agent behaves differently | Write natural user prompts |
| No forbidden behaviors | Misses common failure modes | Add at least one |
| Criteria longer than agent output | Judge confused by detail overload | Keep criteria focused and concise |
| Identical criteria across cases | Doesn't test distinct behaviors | Each case tests something unique |
