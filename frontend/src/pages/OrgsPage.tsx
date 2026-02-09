import { useMemo } from "react";
import { Link } from "react-router-dom";
import { Building2, Package, ArrowRight } from "lucide-react";
import { listSkills } from "../api/client";
import { useApi } from "../hooks/useApi";
import NeonCard from "../components/NeonCard";
import LoadingSpinner from "../components/LoadingSpinner";
import styles from "./OrgsPage.module.css";

interface OrgInfo {
  slug: string;
  skillCount: number;
  totalDownloads: number;
  latestUpdate: string;
}

export default function OrgsPage() {
  const { data: skills, loading, error } = useApi(() => listSkills(), []);

  const orgs = useMemo<OrgInfo[]>(() => {
    if (!skills) return [];
    const map = new Map<string, OrgInfo>();
    for (const s of skills) {
      const existing = map.get(s.org_slug);
      if (existing) {
        existing.skillCount++;
        existing.totalDownloads += s.download_count;
        if (s.updated_at > existing.latestUpdate) {
          existing.latestUpdate = s.updated_at;
        }
      } else {
        map.set(s.org_slug, {
          slug: s.org_slug,
          skillCount: 1,
          totalDownloads: s.download_count,
          latestUpdate: s.updated_at,
        });
      }
    }
    return [...map.values()].sort((a, b) => a.slug.localeCompare(b.slug));
  }, [skills]);

  if (loading) return <LoadingSpinner text="Loading organizations..." />;
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
      <div className={styles.header}>
        <h1 className={styles.title}>
          <Building2 size={28} />
          Organizations
        </h1>
        <p className={styles.subtitle}>
          {orgs.length} organizations with published skills
        </p>
      </div>

      {orgs.length === 0 ? (
        <div className={styles.empty}>
          <Building2 size={48} />
          <p>No organizations found</p>
        </div>
      ) : (
        <div className={styles.grid}>
          {orgs.map((org) => (
            <Link
              key={org.slug}
              to={`/orgs/${org.slug}`}
              className={styles.orgLink}
            >
              <NeonCard glow="purple">
                <div className={styles.card}>
                  <div className={styles.cardIcon}>
                    <Building2 size={32} />
                  </div>
                  <h3 className={styles.cardName}>{org.slug}</h3>
                  <div className={styles.cardStats}>
                    <div className={styles.stat}>
                      <Package size={14} />
                      <span>{org.skillCount} skills</span>
                    </div>
                    <div className={styles.stat}>
                      <span>{org.totalDownloads.toLocaleString()} downloads</span>
                    </div>
                  </div>
                  <div className={styles.cardFooter}>
                    <span>View skills</span>
                    <ArrowRight size={14} />
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
