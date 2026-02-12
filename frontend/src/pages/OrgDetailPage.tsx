import { useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { Package, Download, ArrowLeft, Globe, Github, ChevronLeft, ChevronRight } from "lucide-react";
import { listSkillsFiltered, getOrgProfile } from "../api/client";
import { useApi } from "../hooks/useApi";
import NeonCard from "../components/NeonCard";
import GradeBadge from "../components/GradeBadge";
import LoadingSpinner from "../components/LoadingSpinner";
import OrgAvatar from "../components/OrgAvatar";
import styles from "./OrgDetailPage.module.css";

const PAGE_SIZE = 24;

export default function OrgDetailPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>();
  const [page, setPage] = useState(1);

  const fetchSkills = useCallback(
    () => listSkillsFiltered({ org: orgSlug, sort: "updated", pageSize: PAGE_SIZE, page }),
    [orgSlug, page],
  );

  const { data: skillsData, loading, error } = useApi(fetchSkills, [orgSlug, page]);
  const { data: profile } = useApi(() => getOrgProfile(orgSlug!), [orgSlug]);

  const skills = skillsData?.items ?? [];
  const totalSkills = skillsData?.total ?? 0;
  const totalPages = skillsData?.total_pages ?? 1;

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
              <Package size={14} /> {totalSkills} skills
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

      {totalSkills === 0 ? (
        <div className={styles.empty}>
          <p>No skills published by this organization yet</p>
        </div>
      ) : (
        <>
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

          {totalPages > 1 && (
            <div className={styles.pagination}>
              <button
                className={styles.pageButton}
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                <ChevronLeft size={16} />
                Prev
              </button>
              <span className={styles.pageInfo}>
                Page {page} of {totalPages}
              </span>
              <button
                className={styles.pageButton}
                disabled={page >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                Next
                <ChevronRight size={16} />
              </button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
