import { useMemo, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  Package, Building2, Users, Zap, ArrowRight, Download, Star, Bot, Terminal, Tag,
  ShieldCheck, FlaskConical, Search, Copy, Check
} from "lucide-react";
import { getRegistryStats, listSkillsFiltered } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useCountUp } from "../hooks/useCountUp";
import { useSEO } from "../hooks/useSEO";
import NeonCard from "../components/NeonCard";
import GradeBadge from "../components/GradeBadge";
import AnimatedTerminal from "../components/AnimatedTerminal";
import TerminalBlock from "../components/TerminalBlock";
import styles from "./HomePage.module.css";

const DATA_CATEGORIES = "Data & Database,Data Science & Statistics";
const HOME_PAGE_SIZE = 6;

const INSTALL_COMMANDS = {
  unix: 'curl -LsSf https://astral.sh/uv/install.sh | sh && PATH="$HOME/.local/bin:$PATH" uv tool install dhub-cli',
  windows: 'irm https://astral.sh/uv/install.ps1 | iex; & "$HOME\\.local\\bin\\uv" tool install dhub-cli',
} as const;

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
  const totalPublishers = stats?.total_publishers ?? 0;
  const totalDownloads = stats?.total_downloads ?? 0;

  const jsonLd = useMemo(
    () => ({
      "@context": "https://schema.org",
      "@type": "WebSite",
      name: "Decision Hub",
      url: "https://hub.decision.ai",
      description:
        "The skill registry for AI coding agents. Every skill is automatically evaluated, security-graded, and searchable in natural language.",
    }),
    [],
  );

  useSEO({ path: "/", jsonLd });

  const [animatedSkills, skillsRef] = useCountUp(totalSkills);
  const [animatedOrgs, orgsRef] = useCountUp(totalOrgs);
  const [animatedPublishers, publishersRef] = useCountUp(totalPublishers);
  const [animatedDownloads, downloadsRef] = useCountUp(totalDownloads);

  const [osTab, setOsTab] = useState<"unix" | "windows">("unix");
  const [copied, setCopied] = useState(false);

  const switchOs = useCallback((tab: "unix" | "windows") => {
    setOsTab(tab);
    setCopied(false);
  }, []);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(INSTALL_COMMANDS[osTab]);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [osTab]);

  return (
    <div className="container">
      {/* Hero */}
      <section className={styles.hero}>
        <div className={styles.heroGrid} />
        <h1 className={styles.heroTitle}>
          <span className={styles.heroAccent}>DECISION</span>
          <span className={styles.heroDivider}>//</span>
          <span className={styles.heroMain}>HUB</span>
        </h1>
        <p className={styles.heroSub}>
          The skill registry for AI coding agents.
          Every skill is automatically evaluated, security-graded, and searchable
          in natural language.
        </p>
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

      {/* Stats */}
      <section className={styles.stats}>
        <NeonCard glow="cyan">
          <div className={styles.statItem} ref={skillsRef as React.RefObject<HTMLDivElement>}>
            <Package size={24} className={styles.statIcon} />
            <span className={styles.statNumber}>{animatedSkills.toLocaleString()}</span>
            <span className={styles.statLabel}>Skills Published</span>
          </div>
        </NeonCard>
        <NeonCard glow="pink">
          <div className={styles.statItem} ref={orgsRef as React.RefObject<HTMLDivElement>}>
            <Building2 size={24} className={styles.statIcon} />
            <span className={styles.statNumber}>{animatedOrgs.toLocaleString()}</span>
            <span className={styles.statLabel}>Organizations</span>
          </div>
        </NeonCard>
        <NeonCard glow="purple">
          <div className={styles.statItem} ref={downloadsRef as React.RefObject<HTMLDivElement>}>
            <Download size={24} className={styles.statIcon} />
            <span className={styles.statNumber}>{animatedDownloads.toLocaleString()}</span>
            <span className={styles.statLabel}>Downloads</span>
          </div>
        </NeonCard>
        <NeonCard glow="green">
          <div className={styles.statItem} ref={publishersRef as React.RefObject<HTMLDivElement>}>
            <Users size={24} className={styles.statIcon} />
            <span className={styles.statNumber}>{animatedPublishers.toLocaleString()}</span>
            <span className={styles.statLabel}>Publishers</span>
          </div>
        </NeonCard>
      </section>

      {/* Agent First */}
      <section className={styles.cliSection}>
        <h2 className={styles.sectionTitle}>
          <Bot size={20} />
          Built for Agents
        </h2>
        <p className={styles.sectionSubtitle}>
          Your agent searches the registry, picks a skill, and installs it — all
          inside the conversation. No context switching.
        </p>
        <AnimatedTerminal />
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
                      <span className={styles.skillDownloads}>
                        <Download size={12} />
                        {skill.download_count}
                      </span>
                    </div>
                  </div>
                </NeonCard>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* Install CTA */}
      <section className={styles.installCta}>
        <h2 className={styles.sectionTitle}>
          <Terminal size={20} />
          Install the CLI
        </h2>
        <div className={styles.osToggle}>
          <button
            className={`${styles.osTab} ${osTab === "unix" ? styles.osTabActive : ""}`}
            onClick={() => switchOs("unix")}
          >
            macOS / Linux
          </button>
          <button
            className={`${styles.osTab} ${osTab === "windows" ? styles.osTabActive : ""}`}
            onClick={() => switchOs("windows")}
          >
            Windows
          </button>
        </div>
        <div className={styles.commandWrapper}>
          <TerminalBlock title={osTab === "unix" ? "~" : "PowerShell"}>
            {INSTALL_COMMANDS[osTab]}
          </TerminalBlock>
          <button
            className={styles.copyBtn}
            onClick={handleCopy}
            aria-label="Copy to clipboard"
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </button>
        </div>
        <p className={styles.installAlt}>
          Already have <code>uv</code>? Just run <code>uv tool install dhub-cli</code>
        </p>
      </section>

      {/* Quick Start Examples */}
      <section className={styles.quickStart}>
        <h2 className={styles.sectionTitle}>
          <Zap size={20} />
          Quick Start
        </h2>
        <div className={styles.examplesGrid}>
          <div>
            <p className={styles.exampleLabel}>Search with natural language</p>
            <TerminalBlock title="~">
{`$ dhub ask "how do I analyze time series data?"

╭─ Results for: how do I analyze time series ──╮
│                                               │
│  pymc-labs/time-series — v2.1.0          [A]  │
│  Bayesian time series modeling with PyMC      │
│                                               │
│  datasci/forecast — v1.4.0               [A]  │
│  Prophet-based forecasting toolkit            │
│                                               │
╰───────────────────────────────────────────────╯`}
            </TerminalBlock>
          </div>
          <div>
            <p className={styles.exampleLabel}>Install in one command</p>
            <TerminalBlock title="~">
{`$ dhub install pymc-labs/time-series

Resolving pymc-labs/time-series@latest...
Downloading pymc-labs/time-series@2.1.0...

✓ Installed pymc-labs/time-series@2.1.0
  to ~/.dhub/skills/time-series

✓ Linked to claude, cursor, codex`}
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
              Package your team's agent skills and get automated evals + security
              grading for free. Private by default — only your org can see them.
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
