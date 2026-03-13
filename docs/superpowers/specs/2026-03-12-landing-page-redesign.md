# Landing Page Redesign — Fix New User Confusion

**Date**: 2026-03-12
**Status**: Approved
**Trigger**: User feedback that the landing page is confusing for newcomers — stats-heavy hero, no clear "what is this?" moment, install instructions buried and truncated, unclear how the CLI connects to coding agents.

## Problem Summary

A first-time visitor reported this experience:
1. Eyes go to 7 stat/feature cards in the center — no understanding of what the page is about
2. Subtle subtitle ("Trusted Skills for AI Agents in Data Science and Beyond") is easily missed
3. Install instructions are far down the page, truncated, and require uv with no pip alternative
4. No explanation of how installing `dhub-cli` connects to their coding agent
5. "Ask the Registry" bot rejects meta-questions like "what is this page?"

## Target Audience (Priority Order)

1. **Data scientists / ML engineers** — should install `dhub-cli` and start using skills
2. **AI agent builders / power users** — should integrate the registry into agent workflows
3. **Skill publishers** — should publish their own skills

## Design Decision

**Approach C+**: Narrative funnel hero with a new "Supercharge Your Agent" section below. Keep existing visual style, components, and theme — this is a restructure, not a restyle.

## New Page Flow

### Section 1: Hero (above the fold) — REDESIGNED

**Current**: Big "DECISION // HUB" title → subtle subtitle → "Ask the Registry" + "How It Works" CTAs, followed by 3 value prop cards section, then 4 stat cards section (these are separate `<section>` elements below the hero, not inside it)

**New**:
- **Brand label**: Small pink uppercase "DECISION // HUB" (demoted from headline to label)
- **Headline**: "Your AI agent doesn't know data science." (white) / "Give it a skill that does." (cyan)
- **Subtitle**: "A registry of eval-tested, security-graded skills that make AI coding agents experts — in statistics, ML, causal inference, and beyond."
- **Install command**: Tabbed interface with three tabs:
  - **pip** (default): `pip install dhub-cli`
  - **uv**: `uv tool install dhub-cli`
  - **fresh install**: The curl one-liner that bootstraps uv + installs dhub-cli
- **CTAs**: "Browse Skills" (primary, uses existing `btnPrimary` cyan-to-purple gradient) + "How It Works" (secondary, outlined)
- **Stats bar**: Subtle inline bar below CTAs with a top border separator: "6,800+ skills · 200+ orgs · 50K+ downloads" — replaces the 4 NeonCard stat grid. The publishers stat is intentionally dropped (least meaningful to newcomers). `useCountUp` hook still animates the 3 remaining numbers on scroll; remove the `totalPublishers` call.

**Removed from above-the-fold**:
- 4-card stats section (absorbed into inline stats bar)
- "Ask the Registry" as a hero CTA (still accessible from nav/elsewhere)
- 3 value prop cards (moved to Section 2, which is just below the fold)

### Section 2: Value Props — UNCHANGED

Three NeonCard pillars in a 3-column grid (responsive to 1-col on mobile):
- Automated Evals (cyan glow)
- Security Grading (pink glow)
- Conversational Search (purple glow)

### Section 3: Supercharge Your Agent — NEW

**Replaces**: "Built for Agents" section + standalone install section

**Layout**: Split — left column has 3 numbered steps, right column has the `AnimatedTerminal` component.

**Left column (steps)**:
1. **Install the CLI** — `pip install dhub-cli` — "Your agent can already use dhub commands after this."
2. **Add the dhub skill** — `dhub install decision-ai/dhub-cli` — "Makes your agent more token-efficient and proficient with the registry."
3. **Just ask** — "Tell your agent what you need. It searches the registry, installs the right skill, and gets to work."

**Right column**: The existing `AnimatedTerminal` component with its current script (claude → user prompt → loads dhub skill → searches → installs domain skill → ready).

**Heading**: "Supercharge Your Agent" with bot icon
**Subtitle**: "After installing the CLI, add the dhub skill to give your agent native Decision Hub capabilities — it can search, install, and use skills on its own."

### Section 4: Featured Skills — UNCHANGED

Same skill card grid, same data source (`topSkills`), same styling and layout.

### Section 5: Quick Start — UNCHANGED

Same two-column grid with `dhub ask` and `dhub install` CLI examples.

### Section 6: Publish CTA — UNCHANGED

Same NeonCard with "Publish Your Skills" messaging and two CTAs.

## Sections Removed

| Old Section | Disposition |
|---|---|
| 4-card stats grid | Absorbed into hero as subtle inline bar |
| "Built for Agents" + AnimatedTerminal | Replaced by Section 3 "Supercharge Your Agent" |
| Standalone install section (with OS toggle) | Install moved to hero (tabbed: pip/uv/fresh) + Section 3 step 1 |

## Components

| Component | Change |
|---|---|
| `AnimatedTerminal` | Moved from "Built for Agents" to Section 3. No code changes. |
| `NeonCard` | Still used for value props, skill cards, publish CTA. No longer used for stats. |
| `TerminalBlock` | Still used in Quick Start. No changes. |
| `useCountUp` | Still used for inline stats bar in hero. Target elements change from NeonCard to inline spans. |
| `GradeBadge` | No changes. |
| `SkillCardStats` | No changes. |

## Responsive Behavior

- **Hero**: Headline stacks naturally. Tabbed install stays single-line. Stats bar wraps if needed.
- **Section 3 (Agent)**: Split layout stacks to single column on mobile (steps above terminal).
- All other sections: Same responsive behavior as current page (768px and 480px breakpoints).

## Visual Style

No changes to the design system:
- Same color palette (`--neon-pink`, `--neon-cyan`, `--neon-purple`, `--neon-green`)
- Same typography (Orbitron headings, Rajdhani body, Share Tech Mono code)
- Same CSS custom property scale (`--text-hero` through `--text-xxs`)
- Same dark theme, scanlines, grid background
- Same NeonCard glow effects

## Out of Scope

- **Ask bot meta-question handling**: Tracked separately (see GitHub issue). The bot should handle "what is this?" gracefully with a short explainer + links.
- **"Decision Hub" brand name explanation**: The narrative headline makes the product self-explanatory without needing to justify the brand name.
- **Mobile-specific redesign**: Mobile gets the same responsive stacking as current page. No new mobile-specific components.

## Files to Modify

1. `frontend/src/pages/HomePage.tsx` — Restructure sections, new hero layout, new Section 3, remove stats grid + old install + "Built for Agents"
2. `frontend/src/pages/HomePage.module.css` — New hero styles (brand label, narrative headline, tabbed install, stats bar), new Section 3 styles (split layout, steps), remove old stats grid styles
3. `frontend/src/components/AnimatedTerminal.tsx` — No code changes (just moved in the DOM)

## Verification

After implementation:
- [ ] Take Playwright screenshots at desktop (1440px) and mobile (400px) to verify layout
- [ ] Verify install tabs work (pip/uv/fresh install toggle)
- [ ] Verify AnimatedTerminal still triggers on scroll in its new position
- [ ] Verify useCountUp still works for inline stats bar
- [ ] Check that no dead CSS classes remain from removed sections (including pre-existing orphans like `.howItWorks`, `.stepsGrid`)
- [ ] Verify pip tab is selected by default in the hero install tabs
