import { useParams, Link } from "react-router-dom";
import { Package, Download, ArrowLeft, Globe, Github } from "lucide-react";
import { listSkillsFiltered, getOrgProfile } from "../api/client";
import { useApi } from "../hooks/useApi";
import NeonCard from "../components/NeonCard";
import GradeBadge from "../components/GradeBadge";
import LoadingSpinner from "../components/LoadingSpinner";
import OrgAvatar from "../components/OrgAvatar";
import styles from "./OrgDetailPage.module.css";

export default function OrgDetailPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const { data: skillsData, loading, error } = useApi(
    () => listSkillsFiltered({ org: orgSlug, sort: "updated", pageSize: 100 }),
    [orgSlug]
  );
  const { data: profile } = useApi(() => getOrgProfile(orgSlug!), [orgSlug]);

  const skills = skillsData?.items ?? [];
  const totalDownloads = skills.reduce((sum, s) => sum + s.download_count, 0);

  const blogUrl = profile?.blog
    ? profile.blog.match(/^https?:\/\//) ? profile.blog : `https://${profile.blog}`
    : null;

  if (loading) return <LoadingSpinner text={`Loading ${orgSlug}...`} />;
  if (error) {
    return (
      <div className="container">
        <NeonCard glow="pink">
          <p style={{ color: "var(--neon-pink)" }}>Error: {error}</p>
        </NeonCard>
      </div>
    );
  }

  return (
    <div className="container">
      <Link to="/orgs" className={styles.back}>
        <ArrowLeft size={16} />
        All Organizations
      </Link>

      <div className={styles.header}>
        <OrgAvatar
          avatarUrl={profile?.avatar_url}
          isPersonal={profile?.is_personal ?? false}
          size="lg"
        />
        <div>
          <h1 className={styles.title}>{orgSlug}</h1>
          {profile?.description && (
            <p className={styles.description}>{profile.description}</p>
          )}
          <div className={styles.meta}>
            <span>
              <Package size={14} /> {skills.length} skills
            </span>
            <span>
              <Download size={14} /> {totalDownloads.toLocaleString()} downloads
            </span>
          </div>
          <div className={styles.links}>
            {blogUrl && (
              <a
                href={blogUrl}
                target="_blank"
                rel="noopener noreferrer"
                className={styles.link}
              >
                <Globe size={14} />
                Website
              </a>
            )}
            <a
              href={`https://github.com/${orgSlug}`}
              target="_blank"
              rel="noopener noreferrer"
              className={styles.link}
            >
              <Github size={14} />
              GitHub
            </a>
          </div>
        </div>
      </div>

      {skills.length === 0 ? (
        <div className={styles.empty}>
          <p>No skills published by this organization yet</p>
        </div>
      ) : (
        <div className={styles.grid}>
          {skills.map((skill) => (
            <Link
              key={skill.skill_name}
              to={`/skills/${skill.org_slug}/${skill.skill_name}`}
              className={styles.skillLink}
            >
              <NeonCard glow="cyan">
                <div className={styles.card}>
                  <div className={styles.cardTop}>
                    <h3 className={styles.cardName}>{skill.skill_name}</h3>
                    <GradeBadge grade={skill.safety_rating} size="sm" />
                  </div>
                  <p className={styles.cardDesc}>{skill.description}</p>
                  <div className={styles.cardFooter}>
                    <span className={styles.cardVersion}>
                      v{skill.latest_version}
                    </span>
                    {skill.author && (
                      <span className={styles.cardAuthor}>by {skill.author}</span>
                    )}
                    <span className={styles.cardDownloads}>
                      <Download size={12} />
                      {skill.download_count}
                    </span>
                  </div>
                </div>
              </NeonCard>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
