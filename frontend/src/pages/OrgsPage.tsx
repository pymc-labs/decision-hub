import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { Building2, Package, ArrowRight, Search, Filter } from "lucide-react";
import { listAllSkills, listOrgProfiles } from "../api/client";
import { useApi } from "../hooks/useApi";
import { aggregateOrgs, filterOrgs } from "../lib/filters";
import type { OrgProfile } from "../types/api";
import NeonCard from "../components/NeonCard";
import OrgAvatar from "../components/OrgAvatar";
import LoadingSpinner from "../components/LoadingSpinner";
import styles from "./OrgsPage.module.css";

type OrgType = "orgs" | "users" | "all";

export default function OrgsPage() {
  const { data: skills, loading, error } = useApi(() => listAllSkills(), []);
  const { data: profileList } = useApi(() => listOrgProfiles(), []);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<OrgType>("orgs");

  const profiles = useMemo(() => {
    const map = new Map<string, OrgProfile>();
    for (const p of profileList ?? []) {
      map.set(p.slug, p);
    }
    return map;
  }, [profileList]);

  const orgs = useMemo(
    () => aggregateOrgs(skills ?? []),
    [skills],
  );

  const filtered = useMemo(
    () => filterOrgs(orgs, search, typeFilter),
    [orgs, search, typeFilter],
  );

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
                    <OrgAvatar
                      avatarUrl={profiles.get(org.slug)?.avatar_url}
                      isPersonal={org.isPersonal}
                      size="md"
                    />
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
