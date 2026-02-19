import {
  Search,
  Shield,
  FlaskConical,
  Link,
  Lock,
  GitBranch,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import TerminalBlock from "../components/TerminalBlock";
import { useSEO } from "../hooks/useSEO";
import styles from "./HowItWorksPage.module.css";

interface Feature {
  title: string;
  icon: LucideIcon;
  bullets: ReactNode[];
  terminal: {
    title: string;
    colorCommands: boolean;
    code: string;
  };
}

interface Act {
  label: string;
  color: "cyan" | "pink" | "green";
  tagline: ReactNode;
  features: [Feature, Feature];
}

const ACTS: Act[] = [
  {
    label: "DISCOVER",
    color: "cyan",
    tagline: (
      <>
        Describe your problem, get the right skill — <strong>publish yours and it stays in sync automatically</strong>
      </>
    ),
    features: [
      {
        title: "Conversational Search",
        icon: Search,
        bullets: [
          <>Describe what you need in <strong>plain English</strong> — no catalog browsing, no exact-name guessing</>,
          <><strong>Semantic embedding search</strong> surfaces intent-matched skills, not just keyword hits</>,
          <>Works directly from your agent conversation or from the CLI with <strong>dhub ask</strong></>,
        ],
        terminal: {
          title: "dhub ask",
          colorCommands: true,
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
        icon: GitBranch,
        bullets: [
          <>Point at a repo URL — dhub <strong>discovers every SKILL.md</strong> inside automatically</>,
          <>Repos are <strong>tracked and automatically kept in sync</strong> — push a commit and the registry updates</>,
          <>All discovered skills are <strong>versioned independently</strong> on publish</>,
        ],
        terminal: {
          title: "dhub publish",
          colorCommands: true,
          code: `$ dhub publish git@github.com:pymc-labs/python-analytics-skills.git

Cloning git@github.com:pymc-labs/python-analytics-skills.git...
Found 3 skill(s):
  - pymc-modeling
  - causal-inference
  - time-series

Publishing pymc-modeling...
Published: pymc-labs/pymc-modeling@0.2.0 (Grade A)

Publishing causal-inference...
Published: pymc-labs/causal-inference@0.2.0 (Grade A)

Publishing time-series...
Published: pymc-labs/time-series@0.2.0 (Grade B)

Done: 3 published, 0 skipped, 0 failed`,
        },
      },
    ],
  },
  {
    label: "TRUST",
    color: "pink",
    tagline: (
      <>
        Every skill is <strong>security-graded</strong> and <strong>eval-tested</strong> before anyone installs it
      </>
    ),
    features: [
      {
        title: "The Security Gauntlet",
        icon: Shield,
        bullets: [
          <><strong>Static analysis</strong> catches shell injection, privilege escalation, and data exfiltration patterns</>,
          <><strong>LLM review</strong> adds semantic understanding for prompt injection and policy violations</>,
          <>Letter grades <strong>A–F</strong> appear on every skill card so consumers can make informed decisions</>,
        ],
        terminal: {
          title: "dhub publish",
          colorCommands: true,
          code: `$ dhub publish ./my-skill

Packaging my-skill...
Running security gauntlet...
  ✓ No shell injection patterns
  ✓ No permission escalation
  ✓ No data exfiltration risks
  ✓ No prompt injection vectors

Published: pymc-labs/my-skill@0.1.0 (Grade A)`,
        },
      },
      {
        title: "Automated Evals",
        icon: FlaskConical,
        bullets: [
          <>Extends the SKILL.md format with <strong>eval cases</strong> that define prompts and expected behavior</>,
          <>An <strong>LLM judge</strong> tests two runs: vanilla agent vs. agent with the skill — proving it adds value</>,
          <>Results are <strong>public on every skill page</strong> so anyone can see what the skill does and how well it works</>,
        ],
        terminal: {
          title: "SKILL.md evals section",
          colorCommands: false,
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
    ],
  },
  {
    label: "SHIP",
    color: "green",
    tagline: (
      <>
        Install once, <strong>run on every agent</strong> — keep your team's skills private
      </>
    ),
    features: [
      {
        title: "Write Once, Run Everywhere",
        icon: Link,
        bullets: [
          <>One <strong>--agent all</strong> flag links the skill to Claude, Cursor, Codex, Gemini, and OpenCode</>,
          <>Symlinks live at the path each agent expects — <strong>no per-agent configuration</strong> files</>,
          <>Update the skill once; <strong>all agents pick up the change</strong> on next reload</>,
        ],
        terminal: {
          title: "dhub install",
          colorCommands: true,
          code: `$ dhub install pymc-labs/pymc-modeling --agent all

Resolving pymc-labs/pymc-modeling@latest...
Downloading pymc-labs/pymc-modeling@0.2.0...
Installed pymc-labs/pymc-modeling@0.2.0 to ~/.dhub/skills/pymc-labs/pymc-modeling
Linked to agents: claude, codex, cursor, gemini, opencode`,
        },
      },
      {
        title: "Private by Default",
        icon: Lock,
        bullets: [
          <>Skills published under your org namespace are <strong>only discoverable by org members</strong></>,
          <>Share internal tools, coding standards, and workflows with your team — <strong>not the world</strong></>,
          <><strong>GitHub org membership</strong> is the access gate — no separate IAM system to configure</>,
        ],
        terminal: {
          title: "dhub org",
          colorCommands: true,
          code: `$ dhub org list

Your namespaces:
  lfiaschi        (personal)
  pymc-labs       (organization)

$ dhub config default-org
Select default namespace for publishing:
> pymc-labs`,
        },
      },
    ],
  },
];

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
            <strong>
              Decision Hub is a skill registry where every skill is
              automatically evaluated in a sandbox, security-graded A through F,
              and searchable in plain English. Publish once, install everywhere.
            </strong>
          </p>
        </header>

        <div className={styles.acts}>
          {ACTS.map((act, actIndex) => (
            <section
              key={act.label}
              className={styles.act}
              data-act-color={act.color}
            >
              {actIndex > 0 && <div className={styles.actDivider} />}

              <header className={styles.actHeader}>
                <span className={styles.actLabel}>{act.label}</span>
                <p className={styles.actTagline}>{act.tagline}</p>
              </header>

              <div className={styles.features}>
                {act.features.map((feature, featureIndex) => {
                  const Icon = feature.icon;
                  const isAlternated = featureIndex % 2 === 1;

                  return (
                    <div
                      key={feature.title}
                      className={`${styles.featureRow} ${isAlternated ? styles.featureRowAlt : ""}`}
                    >
                      <div className={styles.featureText}>
                        <div className={styles.featureHeader}>
                          <Icon size={20} className={styles.featureIcon} />
                          <h2 className={styles.featureTitle}>
                            {feature.title}
                          </h2>
                        </div>
                        <ul className={styles.featureBullets}>
                          {feature.bullets.map((bullet, i) => (
                            <li key={i} className={styles.featureBullet}>
                              {bullet}
                            </li>
                          ))}
                        </ul>
                      </div>

                      <div className={styles.featureTerminal}>
                        <TerminalBlock
                          title={feature.terminal.title}
                          colorCommands={feature.terminal.colorCommands}
                        >
                          {feature.terminal.code}
                        </TerminalBlock>
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      </section>
    </div>
  );
}
