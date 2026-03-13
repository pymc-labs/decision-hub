import { useMemo, useState, useCallback, useRef, useEffect } from "react";
import { Link } from "react-router-dom";
import {
  Zap, ArrowRight, Star, Bot, Tag,
  ShieldCheck, FlaskConical, Search, Copy, Check, Package
} from "lucide-react";
import { getRegistryStats, listSkillsFiltered } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useCountUp } from "../hooks/useCountUp";
import { useSEO } from "../hooks/useSEO";
import NeonCard from "../components/NeonCard";
import GradeBadge from "../components/GradeBadge";
import AnimatedTerminal from "../components/AnimatedTerminal";
import SkillCardStats from "../components/SkillCardStats";
import TerminalBlock from "../components/TerminalBlock";
import styles from "./HomePage.module.css";

const DATA_CATEGORIES = "Data Science & Statistics";
const HOME_PAGE_SIZE = 6;

const INSTALL_COMMANDS = {
  pip: "pip install dhub-cli",
  uv: "uv tool install dhub-cli",
  fresh: 'curl -LsSf https://astral.sh/uv/install.sh | sh && PATH="$HOME/.local/bin:$PATH" uv tool install dhub-cli',
} as const;

type InstallTab = keyof typeof INSTALL_COMMANDS;

export default function HomePage() {
  const { data: stats } = useApi(() => getRegistryStats(), []);
  const { data: categorySkills } = useApi(
    () => listSkillsFiltered({ page: 1, pageSize: HOME_PAGE_SIZE, sort: "updated", category: DATA_CATEGORIES }),
    []
  );
  const { data: allSkills } = useApi(
    () => listSkillsFiltered({ page: 1, pageSize: HOME_PAGE_SIZE, sort: "updated" }),
    []
  );

  const topSkills = useMemo(() => {
    const catItems = categorySkills?.items ?? [];
    if (catItems.length >= HOME_PAGE_SIZE) return catItems;
    return allSkills?.items ?? [];
  }, [categorySkills, allSkills]);
  const totalSkills = stats?.total_skills ?? 0;
  const totalOrgs = stats?.total_orgs ?? 0;
  const totalDownloads = stats?.total_downloads ?? 0;

  const jsonLd = useMemo(
    () => ({
      "@context": "https://schema.org",
      "@type": "WebSite",
      name: "Decision Hub",
      url: "https://hub.decision.ai",
      description:
        "Trusted Skills for AI Agents in Data Science and Beyond",
    }),
    [],
  );

  useSEO({ path: "/", jsonLd });

  const [animatedSkills, skillsRef] = useCountUp(totalSkills);
  const [animatedOrgs, orgsRef] = useCountUp(totalOrgs);
  const [animatedDownloads, downloadsRef] = useCountUp(totalDownloads);

  const [installTab, setInstallTab] = useState<InstallTab>("pip");
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => () => clearTimeout(copyTimer.current), []);

  const switchTab = useCallback((tab: InstallTab) => {
    setInstallTab(tab);
    clearTimeout(copyTimer.current);
    setCopied(false);
  }, []);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(INSTALL_COMMANDS[installTab]).then(() => {
      clearTimeout(copyTimer.current);
      setCopied(true);
      copyTimer.current = setTimeout(() => setCopied(false), 2000);
    });
  }, [installTab]);

  return (
    <div className="container">
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
          <div className={styles.installTabs} role="tablist" aria-label="Installation method">
            {(Object.keys(INSTALL_COMMANDS) as InstallTab[]).map((tab) => (
              <button
                key={tab}
                role="tab"
                aria-selected={installTab === tab}
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

      {/* Value Props — the three pillars */}
      <section className={styles.valueProps}>
        <div className={styles.valuePropGrid}>
          <NeonCard glow="cyan">
            <div className={styles.valueProp}>
              <div className={styles.valuePropIcon}>
                <FlaskConical size={32} />
              </div>
              <h3 className={styles.valuePropTitle}>Automated Evals</h3>
              <p className={styles.valuePropDesc}>
                Every skill ships with eval cases. An agent runs each skill in a
                sandbox, and an LLM judge scores the output — so you know a skill
                actually works before you install it.
              </p>
            </div>
          </NeonCard>
          <NeonCard glow="pink">
            <div className={styles.valueProp}>
              <div className={styles.valuePropIcon}>
                <ShieldCheck size={32} />
              </div>
              <h3 className={styles.valuePropTitle}>Security Grading</h3>
              <p className={styles.valuePropDesc}>
                Every submission is automatically analyzed for unsafe patterns —
                arbitrary code execution, data exfiltration, prompt injection — and
                graded A through F. No surprises in your agent's toolchain.
              </p>
            </div>
          </NeonCard>
          <NeonCard glow="purple">
            <div className={styles.valueProp}>
              <div className={styles.valuePropIcon}>
                <Search size={32} />
              </div>
              <h3 className={styles.valuePropTitle}>Conversational Search</h3>
              <p className={styles.valuePropDesc}>
                Describe what you need in plain English. The index understands
                intent, not just keywords — so your agent can find and install the
                right skill in one command.
              </p>
            </div>
          </NeonCard>
        </div>
      </section>

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
              <span className={`${styles.agentStepLabel} ${styles.agentStepLabelCyan}`}>
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
              <span className={`${styles.agentStepLabel} ${styles.agentStepLabelPink}`}>
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
              <span className={`${styles.agentStepLabel} ${styles.agentStepLabelGreen}`}>
                Step 3
              </span>
              <h3 className={styles.agentStepTitle}>Just ask</h3>
              <p className={styles.agentStepDesc}>
                Just tell your agent what you need — it finds, installs, and runs the right skill.
              </p>
            </div>
          </div>
          <AnimatedTerminal />
        </div>
      </section>

      {/* Featured Skills */}
      {topSkills.length > 0 && (
        <section className={styles.featured}>
          <div className={styles.sectionHeader}>
            <h2 className={styles.sectionTitle}>
              <Star size={20} />
              Latest Skills
            </h2>
            <Link to="/skills" className={styles.seeAll}>
              View all <ArrowRight size={14} />
            </Link>
          </div>

          <div className={styles.skillGrid}>
            {topSkills.map((skill) => (
              <Link
                key={`${skill.org_slug}/${skill.skill_name}`}
                to={`/skills/${skill.org_slug}/${skill.skill_name}`}
                className={styles.skillLink}
              >
                <NeonCard glow="cyan">
                  <div className={styles.skillCard}>
                    <div className={styles.skillHeader}>
                      <span className={styles.skillOrg}>{skill.org_slug}</span>
                      <GradeBadge grade={skill.safety_rating} size="sm" />
                    </div>
                    <h3 className={styles.skillName}>{skill.skill_name}</h3>
                    {skill.category && (
                      <div className={styles.skillCategory}>
                        <Tag size={10} />
                        {skill.category}
                      </div>
                    )}
                    <p className={styles.skillDesc}>{skill.description}</p>
                    <div className={styles.skillMeta}>
                      <span className={styles.skillVersion}>
                        v{skill.latest_version}
                      </span>
                      <SkillCardStats
                        github_stars={skill.github_stars}
                        github_license={skill.github_license}
                        download_count={skill.download_count}
                      />
                    </div>
                  </div>
                </NeonCard>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* Quick Start Examples */}
      <section className={styles.quickStart}>
        <h2 className={styles.sectionTitle}>
          <Zap size={20} />
          Quick Start
        </h2>
        <div className={styles.examplesGrid}>
          <div className={styles.exampleCol}>
            <p className={styles.exampleLabel}>Search with natural language</p>
            <TerminalBlock title="~">
              {'$ dhub ask "analyze data with statistics"\n\n'}
              <span className={styles.termOutput}>{`Results for: analyze data with statistics

  anthropics/statistical-analysis  v0.1.0  [A]
  Apply statistical methods to datasets

  anthropics/data-exploration      v0.1.0  [A]
  Profile and explore datasets

  pymc-labs/pymc-modeling          v0.1.2  [A]
  Bayesian statistical modeling with PyMC`}</span>
            </TerminalBlock>
          </div>
          <div className={styles.exampleCol}>
            <p className={styles.exampleLabel}>Install in one command</p>
            <TerminalBlock title="~">
              {'$ dhub install anthropics/statistical-analysis --agent all\n\n'}
              <span className={styles.termOutput}>{`Resolving anthropics/statistical-analysis@latest...
Downloading anthropics/statistical-analysis@0.1.0...

✓ Installed anthropics/statistical-analysis@0.1.0
  to ~/.dhub/skills/statistical-analysis

✓ Linked to claude, cursor, codex`}</span>
            </TerminalBlock>
          </div>
        </div>
      </section>

      {/* Bottom CTA */}
      <section className={styles.bottomCta}>
        <NeonCard glow="pink">
          <div className={styles.bottomCtaInner}>
            <h2 className={styles.bottomCtaTitle}>Publish Your Skills</h2>
            <p className={styles.bottomCtaDesc}>
              Publish your skills with automated evals and security grading.
              Keep them public or restrict access to your org.
            </p>
            <div className={styles.bottomCtaActions}>
              <a
                href="https://github.com/pymc-labs/decision-hub"
                target="_blank"
                rel="noopener noreferrer"
                className={styles.btnPrimary}
              >
                <Package size={18} />
                Get Started
                <ArrowRight size={16} />
              </a>
              <Link to="/how-it-works" className={styles.btnSecondary}>
                <Zap size={18} />
                Learn More
              </Link>
            </div>
          </div>
        </NeonCard>
      </section>
    </div>
  );
}
