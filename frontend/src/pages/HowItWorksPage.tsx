import { Search, Shield, FlaskConical, Link, Lock, GitBranch } from "lucide-react";
import NeonCard from "../components/NeonCard";
import TerminalBlock from "../components/TerminalBlock";
import { useSEO } from "../hooks/useSEO";
import styles from "./HowItWorksPage.module.css";

const SECTIONS = [
  {
    title: "Agents That Extend Themselves",
    glow: "cyan" as const,
    icon: Search,
    text: "Agents discover and install the skills they need mid-conversation. A natural language query searches the registry and returns matching skills with safety grades — ready to install.",
    terminal: {
      title: "dhub ask",
      code: `$ dhub ask "I need to do Bayesian statistics with PyMC"

Searching Decision Hub...

  pymc-labs/pymc-modeling  v0.1.0  Grade A
  Bayesian statistical modeling with PyMC v5+

Install with:
  dhub install pymc-labs/pymc-modeling --agent all`,
    },
  },
  {
    title: "Publish from GitHub",
    glow: "green" as const,
    icon: GitBranch,
    text: "Point dhub publish at a GitHub repo and every skill inside is discovered, versioned, and published automatically. No need to clone manually — just pass the URL.",
    terminal: {
      title: "dhub publish",
      code: `$ dhub publish git@github.com:pymc-labs/python-analytics-skills.git

Cloning git@github.com:pymc-labs/python-analytics-skills.git...
Found 3 skill(s):
  - pymc-modeling
  - causal-inference
  - time-series

Publishing pymc-modeling (from pymc-modeling)...
Published: pymc-labs/pymc-modeling@0.2.0 (Grade A)

Publishing causal-inference (from causal-inference)...
Published: pymc-labs/causal-inference@0.2.0 (Grade A)

Publishing time-series (from time-series)...
Published: pymc-labs/time-series@0.2.0 (Grade B)

Done: 3 published, 0 skipped, 0 failed`,
    },
  },
  {
    title: "The Security Gauntlet",
    glow: "pink" as const,
    icon: Shield,
    text: "Every skill published to the registry passes through static analysis and LLM review. Shell injection detection, permission escalation checks, and dangerous-pattern scanning produce a letter grade from A to F — visible on every skill card.",
    terminal: {
      title: "dhub publish",
      code: `$ dhub publish ./my-skill

Packaging my-skill...
Publishing pymc-labs/my-skill@0.1.0...
Published: pymc-labs/my-skill@0.1.0 (Grade A)
Agent assessment started (run: a1b2c3d4...)
Tailing logs... (Ctrl-C to detach)

[1/2] basic-usage
  PASS (12.3s)
[2/2] edge-cases
  PASS (8.1s)

Assessment complete: 2/2 passed in 20.4s`,
    },
  },
  {
    title: "Automated Evals",
    glow: "purple" as const,
    icon: FlaskConical,
    text: "Define eval cases in YAML right inside your SKILL.md. On each publish the agent executes in an isolated sandbox, and an LLM judge scores the output automatically — giving you a confidence signal before users ever see the skill.",
    terminal: {
      title: "SKILL.md evals section",
      code: `evals:
  - name: "basic-usage"
    prompt: "Build a simple linear regression model"
    expected: "Creates a PyMC model with priors and runs MCMC"
    agent: claude

  - name: "diagnostics"
    prompt: "Check convergence of the model"
    expected: "Uses ArviZ to check r_hat and trace plots"
    agent: claude`,
    },
  },
  {
    title: "Write Once, Run Everywhere",
    glow: "green" as const,
    icon: Link,
    text: "One install command symlinks a skill to every supported agent — Claude, Cursor, Codex, Gemini, OpenCode, and more. No per-agent configuration. Update once, and all agents pick up the change.",
    terminal: {
      title: "dhub install",
      code: `$ dhub install pymc-labs/pymc-modeling --agent all

Resolving pymc-labs/pymc-modeling@latest...
Downloading pymc-labs/pymc-modeling@0.2.0...
Installed pymc-labs/pymc-modeling@0.2.0 to ~/.dhub/skills/pymc-labs/pymc-modeling
Linked to agents: claude, codex, cursor, gemini, opencode`,
    },
  },
  {
    title: "Private by Default",
    glow: "cyan" as const,
    icon: Lock,
    text: "Skills are scoped to GitHub organizations — your team's internal tools stay private with zero configuration. Publish to your org namespace and only members can discover and install them.",
    terminal: {
      title: "dhub org",
      code: `$ dhub org list

Your namespaces:
  lfiaschi        (personal)
  pymc-labs       (organization)

$ dhub config default-org
Select default namespace for publishing:
> pymc-labs`,
    },
  },
] as const;

export default function HowItWorksPage() {
  useSEO({
    title: "How It Works",
    description:
      "Learn how Decision Hub works: publish skills from GitHub, run automated safety analysis and evals, and install to Claude, Cursor, Codex, and more with one command.",
    path: "/how-it-works",
  });

  return (
    <div className="container">
      <section className={styles.page}>
        <header className={styles.intro}>
          <h1 className={styles.pageTitle}>How It Works</h1>
          <p className={styles.pageSubtitle}>
            Decision Hub is a package manager for AI agent skills — publish,
            evaluate, and install executable capabilities across every agent you
            use.
          </p>
        </header>

        <div className={styles.sections}>
          {SECTIONS.map(({ title, glow, icon: Icon, text, terminal }) => (
            <NeonCard key={title} glow={glow}>
              <div className={styles.section}>
                <div className={styles.sectionHeader}>
                  <Icon size={18} className={styles.sectionIcon} />
                  <h2 className={styles.sectionTitle}>{title}</h2>
                </div>
                <p className={styles.sectionText}>{text}</p>
                <TerminalBlock title={terminal.title}>
                  {terminal.code}
                </TerminalBlock>
              </div>
            </NeonCard>
          ))}
        </div>
      </section>
    </div>
  );
}
