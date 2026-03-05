import { useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { Package, ArrowLeft, Globe, Github, Star, Tag, RefreshCw } from "lucide-react";
import { listSkillsFiltered, getOrgProfile } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useInfiniteScroll } from "../hooks/useInfiniteScroll";
import { useSEO } from "../hooks/useSEO";
import Card from "../components/Card";
import GradeBadge from "../components/GradeBadge";
import LoadingSpinner from "../components/LoadingSpinner";
import SkillCardStats from "../components/SkillCardStats";
import OrgAvatar from "../components/OrgAvatar";
import { FEATURED_SET } from "../constants/featuredOrgs";
import styles from "./OrgDetailPage.module.css";

const PAGE_SIZE = 24;

/** Wrapper that forces a full remount when the org changes, resetting all state. */
export default function OrgDetailPage() {
  const { orgSlug } = useParams<{ orgSlug: string }>();
  return <OrgDetailPageInner key={orgSlug} orgSlug={orgSlug!} />;
}

function OrgDetailPageInner({ orgSlug }: { orgSlug: string }) {
  useSEO({
    title: orgSlug,
    description: `View skills published by ${orgSlug} on Decision Hub. Browse their AI agent skills with safety grades and evaluations.`,
    path: `/orgs/${orgSlug}`,
  });

  const fetchPage = useCallback(
    (page: number) =>
      listSkillsFiltered({ org: orgSlug, sort: "updated", pageSize: PAGE_SIZE, page }),
    [orgSlug],
  );

  const { items: skills, total: totalSkills, loading, loadingMore, error, hasMore, sentinelRef, retry } =
    useInfiniteScroll(fetchPage, [orgSlug]);
  const { data: profile, loading: profileLoading, error: profileError } = useApi(() => getOrgProfile(orgSlug), [orgSlug]);

  const blogUrl = profile?.blog
    ? profile.blog.match(/^https?:\/\//) ? profile.blog : `https://${profile.blog}`
    : null;

  if ((loading || profileLoading) && skills.length === 0) return <LoadingSpinner text={`Loading ${orgSlug}...`} />;
  if (error && skills.length === 0) {
    return (
      <div className="container">
        <Card>
          <p style={{ color: "var(--destructive)" }}>Error: {error}</p>
        </Card>
      </div>
    );
  }
  const isOrgNotFound = !loading && !profileLoading && profileError && totalSkills === 0;
  if (isOrgNotFound) {
    const is404 = /API 404\b/.test(profileError);
    return (
      <div className="container" style={{ textAlign: "center", paddingTop: "4rem" }}>
        {is404 ? (
          <>
            <p style={{ fontSize: "4rem", fontWeight: 700, color: "var(--foreground)", margin: 0 }}>404</p>
            <h1 style={{ fontSize: "1.6rem", margin: "0.75rem 0 0.5rem" }}>Organization not found</h1>
            <p style={{ color: "var(--fog)", marginBottom: "2rem" }}>
              <strong>{orgSlug}</strong> doesn&apos;t exist or has no published skills.
            </p>
          </>
        ) : (
          <>
            <p style={{ fontSize: "4rem", fontWeight: 700, color: "var(--foreground)", margin: 0 }}>Error</p>
            <h1 style={{ fontSize: "1.6rem", margin: "0.75rem 0 0.5rem" }}>Something went wrong</h1>
            <p style={{ color: "var(--fog)", marginBottom: "2rem" }}>
              Could not load <strong>{orgSlug}</strong>: {profileError}
            </p>
          </>
        )}
        <Link to="/orgs" style={{ color: "var(--charcoal)" }}>
          ← Browse all organizations
        </Link>
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
          <div className={styles.titleRow}>
            <h1 className={styles.title}>{orgSlug}</h1>
            {FEATURED_SET.has(orgSlug) && (
              <span className={styles.featuredBadge}>
                <Star size={12} />
                Featured
              </span>
            )}
          </div>
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

      {totalSkills === 0 && !loading ? (
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
                <Card>
                  <div className={styles.card}>
                    <div className={styles.cardTop}>
                      <h3 className={styles.cardName}>{skill.skill_name}</h3>
                      <GradeBadge grade={skill.safety_rating} size="sm" />
                    </div>
                    {skill.category && (
                      <div className={styles.cardCategory}>
                        <Tag size={10} />
                        {skill.category}
                      </div>
                    )}
                    <p className={styles.cardDesc}>{skill.description}</p>
                    <div className={styles.cardFooter}>
                      <span className={styles.cardVersion}>
                        v{skill.latest_version}
                      </span>
                      {skill.author && skill.author !== "auto-sync" && (
                        <span className={styles.cardAuthor}>by {skill.author}</span>
                      )}
                      {skill.is_auto_synced && (
                        <span className={styles.cardAuthor} title="Auto-synced from GitHub">
                          <RefreshCw size={12} />
                        </span>
                      )}
                      <SkillCardStats
                        github_stars={skill.github_stars}
                        github_license={skill.github_license}
                        download_count={skill.download_count}
                      />
                    </div>
                  </div>
                </Card>
              </Link>
            ))}
          </div>

          {hasMore && (
            <div ref={sentinelRef} className={styles.sentinel}>
              {loadingMore && <span className={styles.loadingMore}>Loading more skills...</span>}
            </div>
          )}

          {/* Inline error when loading more pages fails */}
          {error && skills.length > 0 && (
            <div className={styles.sentinel}>
              <span className={styles.loadMoreError}>Failed to load more skills.</span>
              <button className={styles.retryBtn} onClick={retry}>Retry</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
