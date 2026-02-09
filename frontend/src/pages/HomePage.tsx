import { Link } from "react-router-dom";
import { Package, Building2, Shield, Zap, ArrowRight, Download, Star } from "lucide-react";
import { listSkills } from "../api/client";
import { useApi } from "../hooks/useApi";
import NeonCard from "../components/NeonCard";
import GradeBadge from "../components/GradeBadge";
import styles from "./HomePage.module.css";

export default function HomePage() {
  const { data: skills } = useApi(() => listSkills(), []);

  const topSkills = skills?.slice(0, 6) ?? [];
  const totalSkills = skills?.length ?? 0;
  const totalOrgs = new Set(skills?.map((s) => s.org_slug)).size;
  const totalDownloads = skills?.reduce((sum, s) => sum + s.download_count, 0) ?? 0;

  return (
    <div className="container">
      {/* Hero */}
      <section className={styles.hero}>
        <div className={styles.heroGrid} />
        <h1 className={styles.heroTitle}>
          <span className={styles.heroAccent}>DECISION</span>
          <span className={styles.heroMain}>HUB</span>
        </h1>
        <p className={styles.heroSub}>
          The skill registry for AI agents. Discover, install, and share
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
          <div className={styles.statItem}>
            <Package size={24} className={styles.statIcon} />
            <span className={styles.statNumber}>{totalSkills}</span>
            <span className={styles.statLabel}>Skills Published</span>
          </div>
        </NeonCard>
        <NeonCard glow="pink">
          <div className={styles.statItem}>
            <Building2 size={24} className={styles.statIcon} />
            <span className={styles.statNumber}>{totalOrgs}</span>
            <span className={styles.statLabel}>Organizations</span>
          </div>
        </NeonCard>
        <NeonCard glow="purple">
          <div className={styles.statItem}>
            <Download size={24} className={styles.statIcon} />
            <span className={styles.statNumber}>{totalDownloads.toLocaleString()}</span>
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
    </div>
  );
}
