import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Link } from "react-router-dom";
import { Building2, Package, ArrowRight, Search, Filter, Star, ArrowUp, ArrowDown } from "lucide-react";
import { listOrgStats } from "../api/client";
import type { OrgSortField } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useSEO } from "../hooks/useSEO";
import type { OrgStatsResponse } from "../types/api";
import NeonCard from "../components/NeonCard";
import OrgAvatar from "../components/OrgAvatar";
import LoadingSpinner from "../components/LoadingSpinner";
import { FEATURED_ORGS, FEATURED_SET } from "../constants/featuredOrgs";
import styles from "./OrgsPage.module.css";

type OrgType = "orgs" | "users" | "all";
const DEBOUNCE_MS = 300;
const CHUNK_SIZE = 24;

export default function OrgsPage() {
  useSEO({
    title: "Organizations",
    description:
      "Browse organizations publishing AI agent skills on Decision Hub. Find teams building tools for data science, machine learning, and more.",
    path: "/orgs",
  });

  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<OrgType>("orgs");
  const [sortBy, setSortBy] = useState<OrgSortField>("slug");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [visibleCount, setVisibleCount] = useState(CHUNK_SIZE);

  const defaultDirFor = (field: OrgSortField): "asc" | "desc" =>
    field === "slug" ? "asc" : "desc";

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
      sort: sortBy,
      sortDir,
    });
  }, [debouncedSearch, typeFilter, sortBy, sortDir]);

  const { data, loading, error } = useApi<OrgStatsResponse>(
    fetchOrgs,
    [debouncedSearch, typeFilter, sortBy, sortDir]
  );

  // Pin featured orgs to top in their defined order; server ordering applies within each group.
  const orgs = useMemo(() => {
    const items = data?.items ?? [];
    return [...items].sort((a, b) => {
      const aFeatured = FEATURED_SET.has(a.slug);
      const bFeatured = FEATURED_SET.has(b.slug);
      if (aFeatured && !bFeatured) return -1;
      if (!aFeatured && bFeatured) return 1;
      if (aFeatured && bFeatured) return FEATURED_ORGS.indexOf(a.slug) - FEATURED_ORGS.indexOf(b.slug);
      return 0; // non-featured: preserve server order
    });
  }, [data]);

  // Reset visible count when data changes (render-time adjustment per React docs:
  // https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes)
  const [prevData, setPrevData] = useState(data);
  if (data !== prevData) {
    setPrevData(data);
    setVisibleCount(CHUNK_SIZE);
  }

  const visibleOrgs = useMemo(() => orgs.slice(0, visibleCount), [orgs, visibleCount]);
  const hasMore = visibleCount < orgs.length;

  // Client-side infinite scroll via IntersectionObserver
  const loadMoreRef = useRef(() => {});
  useEffect(() => {
    loadMoreRef.current = () => {
      setVisibleCount((prev) => {
        const total = orgs.length;
        const next = prev + CHUNK_SIZE;
        return next >= total ? total : next;
      });
    };
  }, [orgs.length]);

  const observerRef = useRef<IntersectionObserver | null>(null);
  const sentinelRef = useCallback((node: HTMLDivElement | null) => {
    if (observerRef.current) {
      observerRef.current.disconnect();
      observerRef.current = null;
    }
    if (node) {
      observerRef.current = new IntersectionObserver(
        (entries) => {
          if (entries[0].isIntersecting) {
            loadMoreRef.current();
          }
        },
        { rootMargin: "200px" },
      );
      observerRef.current.observe(node);
    }
  }, []);

  useEffect(() => {
    return () => observerRef.current?.disconnect();
  }, []);

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

        <div className={styles.sortGroup}>
          <select
            aria-label="Sort organizations by"
            value={sortBy}
            onChange={(e) => {
              const field = e.target.value as OrgSortField;
              setSortBy(field);
              setSortDir(defaultDirFor(field));
            }}
            className={styles.sortSelect}
          >
            <option value="slug">Alphabetical</option>
            <option value="skill_count">Most Skills</option>
            <option value="total_downloads">Most Downloads</option>
            <option value="latest_update">Recently Active</option>
          </select>

          <button
            className={styles.sortDirBtn}
            onClick={() => setSortDir(sortDir === "asc" ? "desc" : "asc")}
            title={sortDir === "asc" ? "Ascending — click to reverse" : "Descending — click to reverse"}
            aria-label="Toggle sort direction"
          >
            {sortDir === "asc" ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
          </button>
        </div>
      </div>

      {orgs.length === 0 ? (
        <div className={styles.empty}>
          <Building2 size={48} />
          <p>No organizations match your filters</p>
        </div>
      ) : (
        <>
          <div className={styles.grid}>
            {visibleOrgs.map((org) => (
              <Link
                key={org.slug}
                to={`/orgs/${org.slug}`}
                className={styles.orgLink}
              >
                <NeonCard glow={FEATURED_SET.has(org.slug) ? "purple" : "cyan"}>
                  <div className={styles.card}>
                    {FEATURED_SET.has(org.slug) && (
                      <div className={styles.featuredBadge}>
                        <Star size={12} />
                        Featured
                      </div>
                    )}
                    <div className={styles.cardIcon}>
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

          {hasMore && (
            <div ref={sentinelRef} className={styles.sentinel}>
              <span className={styles.loadingMore}>Loading more organizations...</span>
            </div>
          )}
        </>
      )}
    </div>
  );
}
