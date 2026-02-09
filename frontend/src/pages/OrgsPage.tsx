import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { Building2, Package, ArrowRight, Search, Filter, User } from "lucide-react";
import { listSkills } from "../api/client";
import { useApi } from "../hooks/useApi";
import NeonCard from "../components/NeonCard";
import LoadingSpinner from "../components/LoadingSpinner";
import styles from "./OrgsPage.module.css";

type OrgType = "orgs" | "users" | "all";

interface OrgInfo {
  slug: string;
  skillCount: number;
  totalDownloads: number;
  latestUpdate: string;
  isPersonal: boolean;
}

export default function OrgsPage() {
  const { data: skills, loading, error } = useApi(() => listSkills(), []);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<OrgType>("orgs");

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
          isPersonal: s.is_personal_org,
        });
      }
    }
    return [...map.values()].sort((a, b) => a.slug.localeCompare(b.slug));
  }, [skills]);

  const filtered = useMemo(() => {
    let result = orgs;

    if (search) {
      const q = search.toLowerCase();
      result = result.filter((o) => o.slug.toLowerCase().includes(q));
    }

    if (typeFilter === "orgs") {
      result = result.filter((o) => !o.isPersonal);
    } else if (typeFilter === "users") {
      result = result.filter((o) => o.isPersonal);
    }

    return result;
  }, [orgs, search, typeFilter]);

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

      <div className={styles.filters}>
        <div className={styles.searchBox}>
          <Search size={16} className={styles.searchIcon} />
          <input
            type="text"
            placeholder="Search organizations..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={styles.searchInput}
          />
        </div>

        <div className={styles.filterGroup}>
          <Filter size={14} />
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as OrgType)}
            className={styles.select}
          >
            <option value="orgs">Organizations</option>
            <option value="users">Users</option>
            <option value="all">All</option>
          </select>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className={styles.empty}>
          <Building2 size={48} />
          <p>No organizations match your filters</p>
        </div>
      ) : (
        <div className={styles.grid}>
          {filtered.map((org) => (
            <Link
              key={org.slug}
              to={`/orgs/${org.slug}`}
              className={styles.orgLink}
            >
              <NeonCard glow="purple">
                <div className={styles.card}>
                  <div className={styles.cardIcon}>
                    {org.isPersonal ? <User size={32} /> : <Building2 size={32} />}
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
