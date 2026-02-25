import { useMemo, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  Building2, Users, Zap, ArrowRight, Download, Star, Bot, Terminal, Tag,
  ShieldCheck, FlaskConical, Search, Copy, Check, MessageCircle, Package,
  GitBranch, Lock, Globe, BarChart3
} from "lucide-react";
import { getRegistryStats, listSkillsFiltered } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useCountUp } from "../hooks/useCountUp";
import { useSEO } from "../hooks/useSEO";
import Card from "../components/Card";
import GradeBadge from "../components/GradeBadge";
import AnimatedTerminal from "../components/AnimatedTerminal";
import TerminalBlock from "../components/TerminalBlock";
import styles from "./HomePage.module.css";
import { SHOW_GITHUB_BUTTONS } from "../featureFlags";

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
        "The trust layer for AI agent toolchains. Every skill is tested, graded, and indexed before it reaches your agent.",
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
        <h1 className={styles.heroTitle}>Decision Hub</h1>
        <p className={styles.heroTagline}>Trust your agent's toolchain.</p>
        <p className={styles.heroSub}>
          Every skill is tested, graded, and indexed before it reaches
          your agent. Extend capabilities without extending risk.
        </p>
        <div className={styles.heroCta}>
          <button
            className={styles.btnPrimary}
            onClick={() => window.dispatchEvent(new CustomEvent("open-ask-modal"))}
          >
            <Search size={18} />
            Search the Registry
          </button>
          <Link to="/how-it-works" className={styles.btnSecondary}>
            How It Works
            <ArrowRight size={16} />
          </Link>
        </div>
      </section>

      {/* Value Props — the three pillars */}
      <section className={styles.valueProps}>
        <div className={styles.valuePropGrid}>
          <Card accent="blue">
            <div className={styles.valueProp}>
              <div className={`${styles.valuePropIcon} ${styles.iconBlue}`}>
                <FlaskConical size={28} />
              </div>
              <h3 className={styles.valuePropTitle}>Proven, not promised</h3>
              <p className={styles.valuePropDesc}>
                Every skill runs through automated evals before it's listed.
                An LLM judge scores the output against real test cases — you
                see exactly how well it performs, not just someone's README.
              </p>
            </div>
          </Card>
          <div className={styles.pipelineArrow}>
            <span className={styles.arrowLine} />
          </div>
          <Card accent="green">
            <div className={styles.valueProp}>
              <div className={`${styles.valuePropIcon} ${styles.iconGreen}`}>
                <ShieldCheck size={28} />
              </div>
              <h3 className={styles.valuePropTitle}>Safety built in</h3>
              <p className={styles.valuePropDesc}>
                Every skill is scanned for unsafe patterns — code execution,
                data exfiltration, prompt injection — and graded A through F
                before publishing. The grade is a contract.
              </p>
            </div>
          </Card>
          <div className={styles.pipelineArrow}>
            <span className={styles.arrowLine} />
          </div>
          <Card accent="violet">
            <div className={styles.valueProp}>
              <div className={`${styles.valuePropIcon} ${styles.iconViolet}`}>
                <Search size={28} />
              </div>
              <h3 className={styles.valuePropTitle}>Your agent finds what it needs</h3>
              <p className={styles.valuePropDesc}>
                Describe a capability in plain English. The semantic
                search index understands intent, not keywords — so your
                agent discovers, evaluates, and installs without leaving
                the conversation.
              </p>
            </div>
          </Card>
        </div>
      </section>

      {/* Stats */}
      <section className={styles.stats}>
        <div className={styles.statItem} ref={skillsRef as React.RefObject<HTMLDivElement>}>
          <span className={styles.statNumber}>{animatedSkills.toLocaleString()}</span>
          <span className={styles.statLabel}>Skills Published</span>
        </div>
        <div className={styles.statDivider} />
        <div className={styles.statItem} ref={orgsRef as React.RefObject<HTMLDivElement>}>
          <span className={styles.statNumber}>{animatedOrgs.toLocaleString()}</span>
          <span className={styles.statLabel}>Organizations</span>
        </div>
        <div className={styles.statDivider} />
        <div className={styles.statItem} ref={downloadsRef as React.RefObject<HTMLDivElement>}>
          <span className={styles.statNumber}>{animatedDownloads.toLocaleString()}</span>
          <span className={styles.statLabel}>Downloads</span>
        </div>
        <div className={styles.statDivider} />
        <div className={styles.statItem} ref={publishersRef as React.RefObject<HTMLDivElement>}>
          <span className={styles.statNumber}>{animatedPublishers.toLocaleString()}</span>
          <span className={styles.statLabel}>Publishers</span>
        </div>
      </section>

      {/* How it's different */}
      <section className={styles.differentiators}>
        <h2 className={styles.sectionTitle} style={{ justifyContent: "center", marginBottom: 24 }}>
          Why Decision Hub
        </h2>
        <div className={styles.diffGrid}>
          <div className={styles.diffItem}>
            <div className={`${styles.diffIcon} ${styles.iconBlue}`}>
              <GitBranch size={20} />
            </div>
            <div>
              <h4 className={styles.diffTitle}>Publish from GitHub</h4>
              <p className={styles.diffDesc}>
                Push to your repo, skills publish automatically. Every commit
                syncs — no manual uploads.
              </p>
            </div>
          </div>
          <div className={styles.diffItem}>
            <div className={`${styles.diffIcon} ${styles.iconViolet}`}>
              <Search size={20} />
            </div>
            <div>
              <h4 className={styles.diffTitle}>Semantic search</h4>
              <p className={styles.diffDesc}>
                Embedding-based index, not keyword matching. Agents find skills
                by describing what they need in plain English.
              </p>
            </div>
          </div>
          <div className={styles.diffItem}>
            <div className={`${styles.diffIcon} ${styles.iconGreen}`}>
              <BarChart3 size={20} />
            </div>
            <div>
              <h4 className={styles.diffTitle}>Automated evals</h4>
              <p className={styles.diffDesc}>
                Real test cases, sandboxed execution, LLM-judged results.
                The eval score ships with every version.
              </p>
            </div>
          </div>
          <div className={styles.diffItem}>
            <div className={`${styles.diffIcon} ${styles.iconBlue}`}>
              <Lock size={20} />
            </div>
            <div>
              <h4 className={styles.diffTitle}>Private skills</h4>
              <p className={styles.diffDesc}>
                Not everything belongs in public. Publish skills scoped to
                your org — visible only to your team.
              </p>
            </div>
          </div>
          <div className={styles.diffItem}>
            <div className={`${styles.diffIcon} ${styles.iconViolet}`}>
              <Building2 size={20} />
            </div>
            <div>
              <h4 className={styles.diffTitle}>Self-host for enterprise</h4>
              <p className={styles.diffDesc}>
                Run the full registry on your own infrastructure.
                Open-source core, no vendor lock-in.
              </p>
            </div>
          </div>
          <div className={styles.diffItem}>
            <div className={`${styles.diffIcon} ${styles.iconGreen}`}>
              <Globe size={20} />
            </div>
            <div>
              <h4 className={styles.diffTitle}>Multi-marketplace</h4>
              <p className={styles.diffDesc}>
                Publish once, distribute everywhere. Automated syndication
                to other skill registries is coming soon.
              </p>
            </div>
          </div>
        </div>
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
                <Card>
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
                </Card>
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
        <div className={styles.bottomCtaInner}>
          <h2 className={styles.bottomCtaTitle}>Your team's expertise, packaged for agents.</h2>
          <p className={styles.bottomCtaDesc}>
            Codify your best practices into skills. Private by default,
            automatically evaluated, version-controlled. Self-host it or
            use our cloud — the code is open source.
          </p>
          <div className={styles.bottomCtaActions}>
            {SHOW_GITHUB_BUTTONS && (
              <a
                href="https://github.com/pymc-labs/decision-hub"
                target="_blank"
                rel="noopener noreferrer"
                className={styles.btnPrimary}
              >
                <Package size={18} />
                Get Started
              </a>
            )}
            <Link to="/how-it-works" className={styles.btnSecondary}>
              Learn More
              <ArrowRight size={16} />
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
