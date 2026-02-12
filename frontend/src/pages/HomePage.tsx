import { Link } from "react-router-dom";
import { Package, Building2, Shield, Zap, ArrowRight, Download, Star, Bot, Terminal } from "lucide-react";
import { getRegistryStats, listSkillsFiltered } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useCountUp } from "../hooks/useCountUp";
import NeonCard from "../components/NeonCard";
import GradeBadge from "../components/GradeBadge";
import AnimatedTerminal from "../components/AnimatedTerminal";
import TerminalBlock from "../components/TerminalBlock";
import styles from "./HomePage.module.css";

export default function HomePage() {
  const { data: stats } = useApi(() => getRegistryStats(), []);
  const { data: latestSkills } = useApi(
    () => listSkillsFiltered({ page: 1, pageSize: 6, sort: "updated" }),
    []
  );

  const topSkills = latestSkills?.items ?? [];
  const totalSkills = stats?.total_skills ?? 0;
  const totalOrgs = stats?.total_orgs ?? 0;
  const totalDownloads = stats?.total_downloads ?? 0;

  const [animatedSkills, skillsRef] = useCountUp(totalSkills);
  const [animatedOrgs, orgsRef] = useCountUp(totalOrgs);
  const [animatedDownloads, downloadsRef] = useCountUp(totalDownloads);

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
          The skill registry for data science agents. Discover, install, and share
          executable skills with built-in safety grading and automated
          evaluations.
        </p>
        <div className={styles.heroCta}>
          <Link to="/skills" className={styles.btnPrimary}>
            <Package size={18} />
            Browse Skills
            <ArrowRight size={16} />
          </Link>
          <Link to="/orgs" className={styles.btnSecondary}>
            <Building2 size={18} />
            Organizations
          </Link>
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
          <div className={styles.statItem}>
            <Shield size={24} className={styles.statIcon} />
            <span className={styles.statNumber}>A-F</span>
            <span className={styles.statLabel}>Safety Grading</span>
          </div>
        </NeonCard>
      </section>

      {/* Agent First */}
      <section className={styles.cliSection}>
        <h2 className={styles.sectionTitle}>
          <Bot size={20} />
          Agentic First
        </h2>
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

      {/* How it works */}
      <section className={styles.howItWorks}>
        <h2 className={styles.sectionTitle}>
          <Zap size={20} />
          How It Works
        </h2>
        <div className={styles.stepsGrid}>
          <NeonCard glow="pink">
            <div className={styles.step}>
              <span className={styles.stepNumber}>01</span>
              <h3 className={styles.stepTitle}>Publish</h3>
              <p className={styles.stepDesc}>
                Package your SKILL.md and source code. Automated safety analysis
                grades every submission A through F.
              </p>
            </div>
          </NeonCard>
          <NeonCard glow="cyan">
            <div className={styles.step}>
              <span className={styles.stepNumber}>02</span>
              <h3 className={styles.stepTitle}>Evaluate</h3>
              <p className={styles.stepDesc}>
                Define eval cases in YAML. Agent executes in a sandbox, LLM
                judge scores the output automatically.
              </p>
            </div>
          </NeonCard>
          <NeonCard glow="purple">
            <div className={styles.step}>
              <span className={styles.stepNumber}>03</span>
              <h3 className={styles.stepTitle}>Install</h3>
              <p className={styles.stepDesc}>
                One command installs to Claude, Cursor, Codex, Gemini, and more.
                Skills are symlinked across all agents.
              </p>
            </div>
          </NeonCard>
        </div>
      </section>

      {/* How to Install */}
      <section className={styles.installSection}>
        <h2 className={styles.sectionTitle}>
          <Terminal size={20} />
          How to Install
        </h2>
        <div className={styles.installGrid}>
          <div className={styles.installStep}>
            <span className={styles.installLabel}>1. Install the CLI</span>
            <TerminalBlock title="~">
              {`# Install the CLI\nuv tool install dhub-cli\n\n# Login via GitHub\ndhub login`}
            </TerminalBlock>
          </div>
          <div className={styles.installStep}>
            <span className={styles.installLabel}>2. Install a skill to your agents</span>
            <TerminalBlock title="~">
              {`# Search for skills\ndhub ask "I need to do Bayesian statistics with PyMC"\n\n# Install to Claude, Cursor, Codex...\ndhub install pymc-labs/pymc-modeling --agent all`}
            </TerminalBlock>
          </div>
        </div>
      </section>
    </div>
  );
}
