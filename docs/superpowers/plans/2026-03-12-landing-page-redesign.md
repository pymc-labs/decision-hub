# Landing Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the Decision Hub landing page so newcomers understand what it is, why they'd want it, and how to install it — all before scrolling.

**Architecture:** This is a frontend-only restructure of `HomePage.tsx` and `HomePage.module.css`. The hero gets a narrative headline + tabbed install. The stats section is replaced by a subtle inline bar. The "Built for Agents" + standalone install sections are replaced by a new "Supercharge Your Agent" section with steps + terminal demo. All other sections remain unchanged.

**Tech Stack:** React 19, TypeScript, CSS Modules, Vitest + React Testing Library

**Spec:** `docs/superpowers/specs/2026-03-12-landing-page-redesign.md`

---

## Chunk 1: Update Tests for New Page Structure

### Task 1: Update hero tests for new headline and brand label

**Files:**
- Modify: `frontend/src/pages/HomePage.test.tsx`

- [ ] **Step 1: Update the hero test to match new content**

Replace the existing hero test with assertions for the new structure:

```tsx
it("renders hero section with narrative headline", async () => {
  renderPage();
  // Brand label
  expect(screen.getByText(/DECISION/)).toBeInTheDocument();
  expect(screen.getByText(/HUB/)).toBeInTheDocument();
  // Narrative headline
  expect(
    screen.getByText("Your AI agent doesn't know data science."),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Give it a skill that does."),
  ).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/HomePage.test.tsx`
Expected: FAIL — old hero content still rendered

### Task 2: Update stats test for inline stats bar

**Files:**
- Modify: `frontend/src/pages/HomePage.test.tsx`

- [ ] **Step 1: Replace stats section test with inline stats bar test**

Replace the `renders stats section labels` test:

```tsx
it("renders inline stats bar in hero", async () => {
  renderPage();

  await waitFor(() => {
    expect(screen.getByText("Skills")).toBeInTheDocument();
    expect(screen.getByText("Organizations")).toBeInTheDocument();
    expect(screen.getByText("Downloads")).toBeInTheDocument();
  });

  // Publishers stat is intentionally dropped
  expect(screen.queryByText("Publishers")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/HomePage.test.tsx`
Expected: FAIL — old stats section still rendered with "Publishers"

### Task 3: Update install tab tests for pip/uv/fresh tabs

**Files:**
- Modify: `frontend/src/pages/HomePage.test.tsx`

- [ ] **Step 1: Replace OS toggle test with install tab test**

Replace the `toggles OS tab and changes install command` test:

```tsx
it("toggles install tabs between pip, uv, and fresh install", async () => {
  const user = userEvent.setup();
  renderPage();

  // Default tab is pip
  expect(screen.getByText("pip install dhub-cli")).toBeInTheDocument();

  // Switch to uv
  const uvTab = screen.getByRole("button", { name: "uv" });
  await user.click(uvTab);
  expect(screen.getByText("uv tool install dhub-cli")).toBeInTheDocument();

  // Switch to fresh install
  const freshTab = screen.getByRole("button", { name: "fresh install" });
  await user.click(freshTab);
  expect(screen.getByText(/curl -LsSf/)).toBeInTheDocument();
});
```

- [ ] **Step 2: Update the clipboard copy test**

Replace the clipboard test to use pip as default:

```tsx
it("copies install command to clipboard on copy button click", async () => {
  const user = userEvent.setup();
  renderPage();

  const clipboardSpy = vi.spyOn(navigator.clipboard, "writeText");

  const copyBtn = screen.getByRole("button", { name: "Copy to clipboard" });
  await user.click(copyBtn);

  expect(clipboardSpy).toHaveBeenCalledWith("pip install dhub-cli");

  clipboardSpy.mockRestore();
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/HomePage.test.tsx`
Expected: FAIL — old OS toggle still rendered

### Task 4: Remove "Ask the Registry" hero CTA test and add agent section test

**Files:**
- Modify: `frontend/src/pages/HomePage.test.tsx`

- [ ] **Step 1: Remove the "Ask the Registry" button test**

Delete the entire `'Ask the Registry' button dispatches open-ask-modal custom event` test. The "Ask the Registry" button is being removed from the hero (it's still in the nav but not tested here).

- [ ] **Step 2: Add test for "Supercharge Your Agent" section**

Add a new test:

```tsx
it("renders Supercharge Your Agent section with steps", async () => {
  renderPage();

  expect(screen.getByText("Supercharge Your Agent")).toBeInTheDocument();
  expect(screen.getByText("Install the CLI")).toBeInTheDocument();
  expect(screen.getByText("Add the dhub skill")).toBeInTheDocument();
  expect(screen.getByText("Just ask")).toBeInTheDocument();
});
```

- [ ] **Step 3: Add test for hero CTAs**

Add a new test:

```tsx
it("renders Browse Skills and How It Works CTAs", async () => {
  renderPage();

  expect(screen.getByText("Browse Skills")).toBeInTheDocument();
  expect(screen.getByText("How It Works")).toBeInTheDocument();

  const browseLink = screen.getByText("Browse Skills").closest("a");
  expect(browseLink).toHaveAttribute("href", "/skills");

  const howItWorksLink = screen.getByText("How It Works").closest("a");
  expect(howItWorksLink).toHaveAttribute("href", "/how-it-works");
});
```

- [ ] **Step 4: Run all tests to confirm they fail**

Run: `cd frontend && npx vitest run src/pages/HomePage.test.tsx`
Expected: FAIL — implementation not yet updated

- [ ] **Step 5: Commit test changes**

```bash
git add frontend/src/pages/HomePage.test.tsx
git commit -m "test: update HomePage tests for landing page redesign

Tests now expect: narrative headline, tabbed install (pip/uv/fresh),
inline stats bar, Supercharge Your Agent section, Browse Skills CTA.
Tests will fail until implementation is updated.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Chunk 2: Implement New Hero Section

### Task 5: Rewrite hero JSX in HomePage.tsx

**Files:**
- Modify: `frontend/src/pages/HomePage.tsx`

- [ ] **Step 1: Update imports — remove unused icons, add new ones**

Replace the icon import line:

```tsx
import {
  Zap, ArrowRight, Star, Bot, Tag,
  ShieldCheck, FlaskConical, Search, Copy, Check, Package
} from "lucide-react";
```

Removed: `Building2`, `Users`, `Download`, `MessageCircle`, `Terminal` (no longer used in page).

- [ ] **Step 2: Update INSTALL_COMMANDS constant for pip/uv/fresh tabs**

Replace the existing `INSTALL_COMMANDS` constant:

```tsx
const INSTALL_COMMANDS = {
  pip: "pip install dhub-cli",
  uv: "uv tool install dhub-cli",
  fresh: 'curl -LsSf https://astral.sh/uv/install.sh | sh && PATH="$HOME/.local/bin:$PATH" uv tool install dhub-cli',
} as const;

type InstallTab = keyof typeof INSTALL_COMMANDS;
```

- [ ] **Step 3: Update state and hooks — remove publishers, change tab type**

Replace the state and hooks section. Change `osTab` to `installTab` with the new type, remove `totalPublishers` const declaration (line 44) and its `useCountUp` call (line 63):

```tsx
const totalSkills = stats?.total_skills ?? 0;
const totalOrgs = stats?.total_orgs ?? 0;
const totalDownloads = stats?.total_downloads ?? 0;

// ...jsonLd and useSEO stay the same...

const [animatedSkills, skillsRef] = useCountUp(totalSkills);
const [animatedOrgs, orgsRef] = useCountUp(totalOrgs);
const [animatedDownloads, downloadsRef] = useCountUp(totalDownloads);

const [installTab, setInstallTab] = useState<InstallTab>("pip");
const [copied, setCopied] = useState(false);

const switchTab = useCallback((tab: InstallTab) => {
  setInstallTab(tab);
  setCopied(false);
}, []);

const handleCopy = useCallback(() => {
  navigator.clipboard.writeText(INSTALL_COMMANDS[installTab]);
  setCopied(true);
  setTimeout(() => setCopied(false), 2000);
}, [installTab]);
```

- [ ] **Step 4: Replace hero JSX**

Replace the entire `{/* Hero */}` section (lines 82-107 in current file) with:

```tsx
{/* Hero */}
<section className={styles.hero}>
  <div className={styles.heroGrid} />
  <span className={styles.heroBrand}>DECISION // HUB</span>
  <h1 className={styles.heroTitle}>
    <span className={styles.heroLine1}>Your AI agent doesn't know data science.</span>
    <span className={styles.heroLine2}>Give it a skill that does.</span>
  </h1>
  <p className={styles.heroSub}>
    A registry of eval-tested, security-graded skills that make AI coding
    agents experts — in statistics, ML, causal inference, and beyond.
  </p>

  {/* Tabbed install */}
  <div className={styles.installBlock}>
    <div className={styles.installTabs}>
      {(Object.keys(INSTALL_COMMANDS) as InstallTab[]).map((tab) => (
        <button
          key={tab}
          className={`${styles.installTab} ${installTab === tab ? styles.installTabActive : ""}`}
          onClick={() => switchTab(tab)}
        >
          {tab === "fresh" ? "fresh install" : tab}
        </button>
      ))}
    </div>
    <div className={styles.installCommand}>
      <code>{INSTALL_COMMANDS[installTab]}</code>
      <button
        className={styles.copyBtn}
        onClick={handleCopy}
        aria-label="Copy to clipboard"
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
    </div>
  </div>

  <div className={styles.heroCta}>
    <Link to="/skills" className={styles.btnPrimary}>
      <Package size={18} />
      Browse Skills
      <ArrowRight size={16} />
    </Link>
    <Link to="/how-it-works" className={styles.btnSecondary}>
      <Zap size={18} />
      How It Works
    </Link>
  </div>

  {/* Inline stats bar */}
  <div className={styles.statsBar}>
    <div className={styles.statInline} ref={skillsRef as React.RefObject<HTMLDivElement>}>
      <span className={styles.statNum}>{animatedSkills.toLocaleString()}</span>
      <span className={styles.statLbl}>Skills</span>
    </div>
    <div className={styles.statInline} ref={orgsRef as React.RefObject<HTMLDivElement>}>
      <span className={styles.statNum}>{animatedOrgs.toLocaleString()}</span>
      <span className={styles.statLbl}>Organizations</span>
    </div>
    <div className={styles.statInline} ref={downloadsRef as React.RefObject<HTMLDivElement>}>
      <span className={styles.statNum}>{animatedDownloads.toLocaleString()}</span>
      <span className={styles.statLbl}>Downloads</span>
    </div>
  </div>
</section>
```

- [ ] **Step 5: Remove old stats section and "Built for Agents" section**

Delete the entire `{/* Stats */}` section and the `{/* Agent First */}` section. Search by section comments (`{/* Stats */}`, `{/* Agent First */}`) rather than line numbers, as line numbers will have shifted after Step 4.

- [ ] **Step 6: Remove old install section**

Delete the entire `{/* Install CTA */}` section. Search by section comment, not line numbers.

- [ ] **Step 7: Run tests**

Run: `cd frontend && npx vitest run src/pages/HomePage.test.tsx`
Expected: Some tests pass (hero, stats bar), some still fail (agent section not yet added)

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/HomePage.tsx
git commit -m "feat: redesign hero with narrative headline and tabbed install

Replace centered title with problem-statement headline, add pip/uv/fresh
install tabs, replace 4-card stats grid with subtle inline stats bar,
remove standalone install and Built for Agents sections.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Chunk 3: Add New Hero and Install CSS

### Task 6: Add CSS for new hero elements

**Files:**
- Modify: `frontend/src/pages/HomePage.module.css`

- [ ] **Step 1: Replace hero CSS (lines 1-67) with new hero styles**

Replace everything from `/* Hero */` through `.heroCta` closing brace:

```css
/* Hero */
.hero {
  text-align: center;
  padding: 60px 0 40px;
  position: relative;
}

.heroGrid {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse at 50% 0%, rgba(0, 240, 255, 0.08) 0%, transparent 60%),
    radial-gradient(ellipse at 20% 50%, rgba(180, 0, 255, 0.05) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 50%, rgba(255, 45, 149, 0.05) 0%, transparent 50%);
  pointer-events: none;
}

.heroBrand {
  display: block;
  font-family: 'Orbitron', sans-serif;
  font-size: var(--text-xs);
  color: var(--neon-pink);
  text-transform: uppercase;
  letter-spacing: 4px;
  margin-bottom: 16px;
  position: relative;
}

.heroTitle {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 20px;
  position: relative;
}

.heroLine1 {
  font-size: var(--text-display);
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.2;
}

.heroLine2 {
  font-size: var(--text-display);
  font-weight: 800;
  color: var(--neon-cyan);
  text-shadow: var(--glow-cyan);
  line-height: 1.2;
}

.heroSub {
  max-width: 560px;
  margin: 0 auto 28px;
  font-size: var(--text-body);
  color: var(--text-secondary);
  line-height: 1.7;
  position: relative;
}

.heroCta {
  display: flex;
  gap: 16px;
  justify-content: center;
  position: relative;
  margin-bottom: 28px;
}
```

- [ ] **Step 2: Add tabbed install styles**

Add after the `.heroCta` block, before the button styles:

```css
/* Tabbed install */
.installBlock {
  max-width: 600px;
  margin: 0 auto 24px;
  position: relative;
}

.installTabs {
  display: inline-flex;
  border: 1px solid var(--border-color);
  border-bottom: none;
  border-radius: 6px 6px 0 0;
  overflow: hidden;
}

.installTab {
  padding: 6px 20px;
  font-family: 'Rajdhani', sans-serif;
  font-size: var(--text-sm);
  font-weight: 600;
  letter-spacing: 0.5px;
  color: var(--text-muted);
  background: transparent;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
}

.installTab:not(:last-child) {
  border-right: 1px solid var(--border-color);
}

.installTabActive {
  color: var(--neon-cyan);
  background: rgba(0, 240, 255, 0.08);
}

.installCommand {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-darkest);
  border: 1px solid var(--border-color);
  border-radius: 0 6px 6px 6px;
  padding: 12px 16px;
  font-family: 'Share Tech Mono', monospace;
  font-size: var(--text-sm);
  color: var(--neon-cyan);
  text-align: left;
  overflow-x: auto;
}

.installCommand code {
  white-space: nowrap;
}
```

- [ ] **Step 3: Add inline stats bar styles**

Add after the install block styles:

```css
/* Inline stats bar */
.statsBar {
  display: flex;
  justify-content: center;
  gap: 40px;
  padding-top: 20px;
  border-top: 1px solid var(--border-color);
  margin-top: 8px;
  position: relative;
}

.statInline {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.statNum {
  font-family: 'Orbitron', sans-serif;
  font-size: var(--text-lg);
  font-weight: 700;
  color: var(--neon-cyan);
}

.statLbl {
  font-size: var(--text-xs);
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
```

- [ ] **Step 4: Remove old stats CSS**

Delete the entire `/* Stats */` block (`.stats`, `.statItem`, `.statIcon`, `.statNumber`, `.statLabel`).

- [ ] **Step 5: Remove old install CTA CSS and update `.copyBtn`**

Delete from the `/* Install CTA */` block: `.installCta`, `.installCta .sectionTitle`, `.osToggle`, `.osTab`, `.osTab:not(:last-child)`, `.osTabActive`, `.commandWrapper`, `.installAlt`, `.installAlt code`.

Keep `.copyBtn` and `.copyBtn:hover` but update `.copyBtn` to work inside the new flex `.installCommand` container — remove absolute positioning and use flex-compatible layout instead:

```css
.copyBtn {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  border-radius: 4px;
  border: 1px solid var(--border-color);
  background: var(--bg-darkest);
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.2s ease;
}
```

- [ ] **Step 6: Remove dead orphan CSS**

Delete the entire `/* How it works */` block that's never used: `.howItWorks`, `.howItWorks .sectionTitle`, `.stepsGrid`, `.step`, `.stepNumber`, `.stepTitle`, `.stepDesc`.

- [ ] **Step 7: Update responsive breakpoints**

In the `@media (max-width: 768px)` block:
- Remove `.heroTitle` font-size override (the new headline uses flex-direction: column naturally)
- Remove `.heroDivider` override (no longer exists)
- Remove `.stats` grid-template-columns override (stats section removed)
- Remove `.stepsGrid` from the grid-template-columns rule
- Add new responsive rules:

```css
.heroLine1,
.heroLine2 {
  font-size: var(--text-title);
}

.statsBar {
  gap: 24px;
}

.agentGrid {
  grid-template-columns: 1fr;
}
```

In the `@media (max-width: 480px)` block:
- Remove `.heroTitle` overrides (flex-direction, gap, font-size)
- Remove `.heroDivider` override
- Remove `.statNumber`, `.statLabel` overrides (old stats section gone)
- Remove `.howItWorks` and `.installCta` from the margin rule (`.featured, .howItWorks, .installCta, .quickStart` → `.featured, .quickStart`)
- Remove `.cliSection` override (section removed)
- Remove `.stepNumber` override
- Add new responsive rules:

```css
.heroBrand {
  font-size: var(--text-xxs);
}

.heroLine1,
.heroLine2 {
  font-size: var(--text-heading);
}

.statsBar {
  flex-direction: column;
  gap: 12px;
  align-items: center;
}

.statNum {
  font-size: var(--text-body);
}
```

- [ ] **Step 8: Run tests**

Run: `cd frontend && npx vitest run src/pages/HomePage.test.tsx`
Expected: Hero and stats tests should pass now

- [ ] **Step 9: Run lint**

Run: `cd frontend && npx tsc -b && npx eslint .`
Expected: No errors

- [ ] **Step 10: Commit**

```bash
git add frontend/src/pages/HomePage.module.css
git commit -m "style: add CSS for new hero layout, tabbed install, inline stats bar

New styles for brand label, narrative headline, tabbed install block,
inline stats bar. Remove old stats grid, install CTA, and dead
howItWorks/stepsGrid CSS. Update responsive breakpoints.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Chunk 4: Implement "Supercharge Your Agent" Section

### Task 7: Add "Supercharge Your Agent" section JSX

**Files:**
- Modify: `frontend/src/pages/HomePage.tsx`

- [ ] **Step 1: Add the new section after value props, before featured skills**

Insert after the `{/* Value Props */}` section closing tag and before `{/* Featured Skills */}`:

```tsx
{/* Supercharge Your Agent */}
<section className={styles.agentSection}>
  <h2 className={styles.sectionTitle}>
    <Bot size={20} />
    Supercharge Your Agent
  </h2>
  <p className={styles.sectionSubtitle}>
    After installing the CLI, add the dhub skill to give your agent native
    Decision Hub capabilities — it can search, install, and use skills on its own.
  </p>
  <div className={styles.agentGrid}>
    <div className={styles.agentSteps}>
      <div className={styles.agentStep}>
        <span className={styles.agentStepLabel} style={{ color: "var(--neon-cyan)" }}>
          Step 1
        </span>
        <h3 className={styles.agentStepTitle}>Install the CLI</h3>
        <div className={styles.agentStepCommand}>
          <code>pip install dhub-cli</code>
        </div>
        <p className={styles.agentStepDesc}>
          Your agent can already use dhub commands after this.
        </p>
      </div>
      <div className={styles.agentStep}>
        <span className={styles.agentStepLabel} style={{ color: "var(--neon-pink)" }}>
          Step 2
        </span>
        <h3 className={styles.agentStepTitle}>Add the dhub skill</h3>
        <div className={styles.agentStepCommand}>
          <code>dhub install decision-ai/dhub-cli</code>
        </div>
        <p className={styles.agentStepDesc}>
          Makes your agent more token-efficient and proficient with the registry.
        </p>
      </div>
      <div className={styles.agentStep}>
        <span className={styles.agentStepLabel} style={{ color: "var(--neon-green)" }}>
          Step 3
        </span>
        <h3 className={styles.agentStepTitle}>Just ask</h3>
        <p className={styles.agentStepDesc}>
          Tell your agent what you need. It searches the registry, installs the
          right skill, and gets to work.
        </p>
      </div>
    </div>
    <AnimatedTerminal />
  </div>
</section>
```

- [ ] **Step 2: Run tests**

Run: `cd frontend && npx vitest run src/pages/HomePage.test.tsx`
Expected: All tests pass including "Supercharge Your Agent" test

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/HomePage.tsx
git commit -m "feat: add Supercharge Your Agent section with steps + terminal demo

Three-step onboarding (install CLI, add skill, just ask) with the
AnimatedTerminal demo showing the full agent workflow.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

### Task 8: Add CSS for "Supercharge Your Agent" section

**Files:**
- Modify: `frontend/src/pages/HomePage.module.css`

- [ ] **Step 1: Add agent section styles**

Replace the old `/* Agent Section */` block (`.cliSection` rules) with:

```css
/* Agent Section */
.agentSection {
  margin: 56px 0;
}

.agentSection .sectionTitle {
  margin-bottom: 8px;
}

.agentGrid {
  display: grid;
  grid-template-columns: 1fr 1.3fr;
  gap: 28px;
  align-items: start;
  margin-top: 24px;
}

.agentSteps {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.agentStep {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.agentStepLabel {
  font-family: 'Orbitron', sans-serif;
  font-size: var(--text-xs);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.agentStepTitle {
  font-size: var(--text-body);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: 0;
}

.agentStepCommand {
  background: var(--bg-darkest);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 8px 12px;
  font-family: 'Share Tech Mono', monospace;
  font-size: var(--text-sm);
  color: var(--neon-cyan);
  width: fit-content;
}

.agentStepDesc {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.5;
}
```

- [ ] **Step 2: Ensure `.agentGrid` is in the 768px responsive block**

Verify this was added in Task 6 Step 7. The rule should be:

```css
.agentGrid {
  grid-template-columns: 1fr;
}
```

- [ ] **Step 3: Run tests**

Run: `cd frontend && npx vitest run src/pages/HomePage.test.tsx`
Expected: All tests pass

- [ ] **Step 4: Run lint**

Run: `cd frontend && npx tsc -b && npx eslint .`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/HomePage.module.css
git commit -m "style: add CSS for Supercharge Your Agent section

Split layout with steps on left, terminal demo on right.
Stacks to single column on mobile.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

## Chunk 5: Verification and Cleanup

### Task 9: Run full test suite and lint

**Files:** None (verification only)

- [ ] **Step 1: Run all frontend tests**

Run: `make test-frontend`
Expected: All tests pass

- [ ] **Step 2: Run frontend lint**

Run: `make lint-frontend`
Expected: No errors

- [ ] **Step 3: Check for unused CSS classes**

Search `HomePage.module.css` for any class that is not referenced in `HomePage.tsx`. Look specifically for:
- `.stats`, `.statItem`, `.statIcon`, `.statNumber`, `.statLabel` — should be deleted
- `.cliSection` — should be deleted (replaced by `.agentSection`)
- `.howItWorks`, `.stepsGrid`, `.step`, `.stepNumber`, `.stepTitle`, `.stepDesc` — should be deleted
- `.installCta`, `.osToggle`, `.osTab`, `.osTabActive`, `.commandWrapper`, `.installAlt` — should be deleted
- `.heroAccent`, `.heroDivider`, `.heroMain` — should be deleted (old hero title)

- [ ] **Step 4: Check for unused imports in HomePage.tsx**

Verify these icons are no longer imported: `Building2`, `Users`, `Download`, `MessageCircle`, `Terminal`.

### Task 10: Visual verification with Playwright screenshots

**Files:** None (verification only)

- [ ] **Step 1: Start the dev server**

Run: `cd frontend && npx vite --port 5174 &`

- [ ] **Step 2: Take desktop screenshot (1440px)**

Use Playwright MCP or agent-browser to navigate to `http://localhost:5174` at 1440px width and take a full-page screenshot. Verify:
- Brand label is small and pink
- Narrative headline is prominent
- Tabbed install shows pip as default
- Stats bar is subtle with 3 numbers
- Value props section appears below
- "Supercharge Your Agent" section has split layout with steps + terminal
- Featured skills, Quick Start, and Publish CTA are unchanged

- [ ] **Step 3: Take mobile screenshot (400px)**

Resize to 400px width and take a screenshot. Verify:
- Headline text scales down appropriately
- Install tabs stay readable
- Stats bar stacks vertically
- Agent section stacks (steps above terminal)
- All text is readable, nothing overflows

- [ ] **Step 4: Verify install tab interaction**

Click through pip → uv → fresh install tabs. Verify:
- pip tab shows `pip install dhub-cli`
- uv tab shows `uv tool install dhub-cli`
- fresh install tab shows the curl one-liner
- Copy button works for each tab

- [ ] **Step 5: Verify AnimatedTerminal triggers on scroll**

Scroll down to the "Supercharge Your Agent" section. Verify the terminal animation starts playing when it enters the viewport.

- [ ] **Step 6: Stop the dev server**

- [ ] **Step 7: Commit any cleanup fixes**

If any issues were found and fixed during verification:

```bash
git add frontend/src/pages/HomePage.tsx frontend/src/pages/HomePage.module.css
git commit -m "fix: cleanup from visual verification

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```
