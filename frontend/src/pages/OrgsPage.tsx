import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Link } from "react-router-dom";
import { Building2, Package, ArrowRight, Search, Filter, Star } from "lucide-react";
import { listOrgStats } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { OrgStatsResponse } from "../types/api";
import NeonCard from "../components/NeonCard";
import OrgAvatar from "../components/OrgAvatar";
import LoadingSpinner from "../components/LoadingSpinner";
import { FEATURED_ORGS, FEATURED_SET } from "../constants/featuredOrgs";
import styles from "./OrgsPage.module.css";

type OrgType = "orgs" | "users" | "all";
const DEBOUNCE_MS = 300;

export default function OrgsPage() {
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<OrgType>("orgs");

  // Debounce the search input
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    debounceRef.current = setTimeout(() => {
      setDebouncedSearch(searchInput);
    }, DEBOUNCE_MS);
    return () => clearTimeout(debounceRef.current);
  }, [searchInput]);

  const fetchOrgs = useCallback(() => {
    return listOrgStats({
      search: debouncedSearch || undefined,
      typeFilter,
    });
  }, [debouncedSearch, typeFilter]);

  const { data, loading, error } = useApi<OrgStatsResponse>(
    fetchOrgs,
    [debouncedSearch, typeFilter]
  );

  const orgs = useMemo(() => {
    const items = data?.items ?? [];
    return [...items].sort((a, b) => {
      const aFeatured = FEATURED_SET.has(a.slug);
      const bFeatured = FEATURED_SET.has(b.slug);
      if (aFeatured && !bFeatured) return -1;
      if (!aFeatured && bFeatured) return 1;
      if (aFeatured && bFeatured) {
        return FEATURED_ORGS.indexOf(a.slug) - FEATURED_ORGS.indexOf(b.slug);
      }
      return 0;
    });
  }, [data]);

  if (loading && !data) return <LoadingSpinner text="Loading organizations..." />;
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
          {orgs.length} organizations found
        </p>
      </div>

      <div className={styles.filters}>
        <div className={styles.searchBox}>
          <Search size={16} className={styles.searchIcon} />
          <input
            type="text"
            placeholder="Search organizations..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
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

      {orgs.length === 0 ? (
        <div className={styles.empty}>
          <Building2 size={48} />
          <p>No organizations match your filters</p>
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
                  {FEATURED_SET.has(org.slug) && (
                    <div className={styles.featuredBadge}>
                      <Star size={12} />
                      Featured
                    </div>
                  )}
                  <div className={`${styles.cardIcon} ${FEATURED_SET.has(org.slug) ? styles.cardIconFeatured : ""}`}>
                    <OrgAvatar
                      avatarUrl={org.avatar_url}
                      isPersonal={org.is_personal}
                      size="md"
                    />
                  </div>
                  <h3 className={styles.cardName}>{org.slug}</h3>
                  <div className={styles.cardStats}>
                    <div className={styles.stat}>
                      <Package size={14} />
                      <span>{org.skill_count} skills</span>
                    </div>
                    <div className={styles.stat}>
                      <span>{org.total_downloads.toLocaleString()} downloads</span>
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
