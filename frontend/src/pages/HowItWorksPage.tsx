import { Search, Shield, FlaskConical, Link, Lock } from "lucide-react";
import NeonCard from "../components/NeonCard";
import TerminalBlock from "../components/TerminalBlock";
import styles from "./HowItWorksPage.module.css";

const SECTIONS = [
  {
    title: "Agents That Extend Themselves",
    glow: "cyan" as const,
    icon: Search,
    text: "Agents discover and install the skills they need mid-conversation. A single command lets an agent search the registry, evaluate options, and wire up new capabilities — no manual setup required.",
    terminal: {
      title: "dhub ask",
      code: `$ dhub ask "I need to lint Dockerfiles"\n\nSearching skills...\nFound: dockerlint (A grade, 342 downloads)\nInstalling dockerlint for claude, cursor...\nDone. Skill is ready to use.`,
    },
  },
  {
    title: "The Security Gauntlet",
    glow: "pink" as const,
    icon: Shield,
    text: "Every skill published to the registry passes through static analysis. Shell injection detection, permission escalation checks, and dangerous-pattern scanning produce a letter grade from A to F — visible on every skill card.",
    terminal: {
      title: "dhub publish",
      code: `$ dhub publish ./my-skill\n\nAnalyzing SKILL.md...\nRunning security checks...\n  Shell injection:     PASS\n  Permission escalation: PASS\n  Dangerous patterns:  PASS\nSafety grade: A\nPublished my-skill v1.0.0`,
    },
  },
  {
    title: "Automated Evals",
    glow: "purple" as const,
    icon: FlaskConical,
    text: "Define eval cases in YAML right inside your skill. On each publish the agent executes in an isolated sandbox, and an LLM judge scores the output automatically — giving you a confidence signal before users ever see the skill.",
    terminal: {
      title: "SKILL.md evals section",
      code: `evals:\n  - name: "basic lint"\n    prompt: "Lint the Dockerfile in this repo"\n    expected: "Reports missing HEALTHCHECK"\n    agent: claude\n\n  - name: "fix mode"\n    prompt: "Fix all lint issues"\n    expected: "Adds HEALTHCHECK instruction"\n    agent: claude`,
    },
  },
  {
    title: "Write Once, Run Everywhere",
    glow: "green" as const,
    icon: Link,
    text: "One install command symlinks a skill to every supported agent — Claude, Cursor, Codex, Gemini, OpenCode, and more. No per-agent configuration. Update once, and all agents pick up the change.",
    terminal: {
      title: "dhub install",
      code: `$ dhub install acme/dockerlint\n\nInstalling acme/dockerlint v2.1.0...\nLinked to:\n  ~/.claude/skills/acme/dockerlint\n  ~/.cursor/skills/acme/dockerlint\n  ~/.codex/skills/acme/dockerlint\n  ~/.gemini/skills/acme/dockerlint\nDone.`,
    },
  },
  {
    title: "Private by Default",
    glow: "cyan" as const,
    icon: Lock,
    text: "Skills are scoped to GitHub organizations — your team's internal tools stay private with zero configuration. Publish to your org namespace and only members can discover and install them.",
    terminal: {
      title: "dhub org",
      code: `$ dhub org list\n\nOrganizations:\n  acme-corp     12 skills   8 members\n  ml-platform    5 skills   4 members\n\n$ dhub install acme-corp/internal-tool\nInstalled (private).`,
    },
  },
] as const;

export default function HowItWorksPage() {
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
