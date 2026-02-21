import { useState, useMemo, useEffect, useRef, useCallback } from "react";
import { Link } from "react-router-dom";
import { Search, Package, Download, Filter, User, Tag, Layers } from "lucide-react";
import { listSkillsFiltered, getTaxonomy, listOrgProfiles, getRegistryStats } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useInfiniteScroll } from "../hooks/useInfiniteScroll";
import { useSEO } from "../hooks/useSEO";
import type { SkillSummary } from "../types/api";
import NeonCard from "../components/NeonCard";
import GradeBadge from "../components/GradeBadge";
import LoadingSpinner from "../components/LoadingSpinner";
import styles from "./SkillsPage.module.css";

const PAGE_SIZE = 12;
const DEBOUNCE_MS = 300;

export default function SkillsPage() {
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [orgFilter, setOrgFilter] = useState<string>("all");
  const [gradeFilter, setGradeFilter] = useState<string>("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [sortBy, setSortBy] = useState<"name" | "downloads" | "updated">("updated");
  const [viewMode, setViewMode] = useState<"grid" | "grouped">("grid");

  useSEO({
    title: "Skills",
    description:
      "Browse the Decision Hub skill registry. Search and filter AI agent skills by category, safety grade, and organization.",
    path: "/skills",
  });

  const { data: taxonomy } = useApi(() => getTaxonomy(), []);
  const { data: orgProfiles } = useApi(() => listOrgProfiles(), []);
  const { data: stats } = useApi(() => getRegistryStats(), []);
  const activeCategories = useMemo(
    () => new Set(stats?.active_categories ?? []),
    [stats],
  );

  // Debounce the search input
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    debounceRef.current = setTimeout(() => {
      setDebouncedSearch(searchInput);
    }, DEBOUNCE_MS);
    return () => clearTimeout(debounceRef.current);
  }, [searchInput]);

  // Build API fetcher for infinite scroll
  const fetchPage = useCallback(
    (page: number) =>
      listSkillsFiltered({
        page,
        pageSize: PAGE_SIZE,
        search: debouncedSearch || undefined,
        org: orgFilter !== "all" ? orgFilter : undefined,
        category: categoryFilter !== "all" ? categoryFilter : undefined,
        grade: gradeFilter !== "all" ? gradeFilter : undefined,
        sort: sortBy,
      }),
    [debouncedSearch, orgFilter, categoryFilter, gradeFilter, sortBy],
  );

  const { items, total, loading, loadingMore, error, hasMore, sentinelRef, retry } =
    useInfiniteScroll(fetchPage, [debouncedSearch, orgFilter, categoryFilter, gradeFilter, sortBy]);

  const orgs = useMemo(
    () => (orgProfiles ?? []).map((p) => p.slug).sort(),
    [orgProfiles],
  );

  const groupedSkills = useMemo(() => {
    const groups: Record<string, SkillSummary[]> = {};
    for (const skill of items) {
      const cat = skill.category || "Uncategorized";
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(skill);
    }
    return groups;
  }, [items]);

  if (loading && items.length === 0) return <LoadingSpinner text="Loading skills..." />;
  if (error && items.length === 0) {
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
          <Package size={28} />
          Skill Registry
        </h1>
        <p className={styles.subtitle}>
          {total} skills — each automatically evaluated and security-graded
        </p>
      </div>

      {/* Filters bar */}
      <div className={styles.filters}>
        <div className={styles.searchBox}>
          <Search size={16} className={styles.searchIcon} />
          <input
            type="text"
            placeholder="Search skills, e.g. 'Bayesian modeling' or 'time series forecasting'..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className={styles.searchInput}
          />
        </div>

        <div className={styles.filterGroup}>
          <Filter size={14} />
          <select
            value={orgFilter}
            onChange={(e) => setOrgFilter(e.target.value)}
            className={styles.select}
          >
            <option value="all">All Orgs</option>
            {orgs.map((org) => (
              <option key={org} value={org}>
                {org}
              </option>
            ))}
          </select>

          <select
            value={gradeFilter}
            onChange={(e) => setGradeFilter(e.target.value)}
            className={styles.select}
          >
            <option value="all">All Grades</option>
            <option value="A">A - Safe</option>
            <option value="B">B - Elevated</option>
            <option value="C">C - Risky</option>
          </select>

          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className={styles.select}
          >
            <option value="all">All Categories</option>
            {Object.entries(taxonomy?.groups ?? {}).map(([group, subcategories]) => {
              const activeSubs = subcategories.filter((sub) => activeCategories.has(sub));
              if (activeSubs.length === 0) return null;
              return (
                <optgroup key={group} label={group}>
                  {activeSubs.map((sub) => (
                    <option key={sub} value={sub}>
                      {sub}
                    </option>
                  ))}
                </optgroup>
              );
            })}
          </select>

          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as "name" | "downloads" | "updated")}
            className={styles.select}
          >
            <option value="updated">Latest</option>
            <option value="name">Name</option>
            <option value="downloads">Downloads</option>
          </select>

          <button
            className={`${styles.viewToggle} ${viewMode === "grouped" ? styles.viewToggleActive : ""}`}
            onClick={() => setViewMode(viewMode === "grid" ? "grouped" : "grid")}
            title={viewMode === "grid" ? "Group by category" : "Flat grid view"}
          >
            <Layers size={16} />
          </button>
        </div>
      </div>

      {/* Results */}
      {items.length === 0 && !loading ? (
        <div className={styles.empty}>
          <Package size={48} />
          <p>No skills match your filters</p>
        </div>
      ) : viewMode === "grouped" ? (
        <div className={styles.groupedContainer}>
          {Object.entries(groupedSkills).map(([category, categorySkills]) => (
            <section key={category} className={styles.categorySection}>
              <h2 className={styles.categoryHeading}>
                <Tag size={16} />
                {category}
                <span className={styles.categoryCount}>{categorySkills.length}</span>
              </h2>
              <div className={styles.grid}>
                {categorySkills.map((skill) => (
                  <SkillCard key={`${skill.org_slug}/${skill.skill_name}`} skill={skill} />
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <div className={styles.grid}>
          {items.map((skill) => (
            <SkillCard key={`${skill.org_slug}/${skill.skill_name}`} skill={skill} />
          ))}
        </div>
      )}

      {/* Infinite scroll sentinel */}
      {hasMore && (
        <div ref={sentinelRef} className={styles.sentinel}>
          {loadingMore && <span className={styles.loadingMore}>Loading more skills...</span>}
        </div>
      )}

      {/* Inline error when loading more pages fails */}
      {error && items.length > 0 && (
        <div className={styles.sentinel}>
          <span className={styles.loadMoreError}>Failed to load more skills.</span>
          <button className={styles.retryBtn} onClick={retry}>Retry</button>
        </div>
      )}
    </div>
  );
}

function SkillCard({ skill }: { skill: SkillSummary }) {
  return (
    <Link
      to={`/skills/${skill.org_slug}/${skill.skill_name}`}
      className={styles.skillLink}
    >
      <NeonCard glow="cyan">
        <div className={styles.card}>
          <div className={styles.cardTop}>
            <div className={styles.cardOrg}>
              <User size={12} />
              {skill.org_slug}
            </div>
            <GradeBadge grade={skill.safety_rating} size="sm" />
          </div>

          <h3 className={styles.cardName}>{skill.skill_name}</h3>

          {skill.category && (
            <div className={styles.cardCategory}>
              <Tag size={10} />
              {skill.category}
            </div>
          )}

          {skill.source_repo_removed && (
            <div className={styles.cardRemoved}>Removed from GitHub</div>
          )}

          <p className={styles.cardDesc}>{skill.description}</p>

          <div className={styles.cardFooter}>
            <span className={styles.cardVersion}>v{skill.latest_version}</span>
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
  );
}
