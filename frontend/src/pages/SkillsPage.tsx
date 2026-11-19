import { useState, useMemo, useEffect, useLayoutEffect, useRef, useCallback } from "react";
import { Link, useLocation, useNavigate, useNavigationType } from "react-router-dom";
import { Search, Package, Filter, User, Tag, Layers, ArrowUp, ArrowDown, RefreshCw } from "lucide-react";
import { listSkillsFiltered, getTaxonomy, listOrgProfiles, getRegistryStats } from "../api/client";
import type { SkillSortField } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useInfiniteScroll } from "../hooks/useInfiniteScroll";
import { useSEO } from "../hooks/useSEO";
import type { SkillSummary } from "../types/api";
import NeonCard from "../components/NeonCard";
import GradeBadge from "../components/GradeBadge";
import LoadingSpinner from "../components/LoadingSpinner";
import SkillCardStats from "../components/SkillCardStats";
import styles from "./SkillsPage.module.css";

const PAGE_SIZE = 12;
const DEBOUNCE_MS = 300;
const MAX_SEARCH_LENGTH = 200;
const MAX_FACET_LENGTH = 100;
const SORT_OPTIONS = [
  ["updated", "Latest"],
  ["name", "Name"],
  ["downloads", "Downloads"],
  ["github_stars", "Stars"],
  ["safety_rating", "Safety"],
] as const satisfies ReadonlyArray<readonly [SkillSortField, string]>;
const GRADES = [["A", "Safe"], ["B", "Elevated"], ["C", "Risky"]] as const;

function defaultDirFor(field: SkillSortField) {
  return field === "name" || field === "safety_rating" ? "asc" : "desc";
}

function queryText(raw: string | null) {
  return (raw ?? "").replace(/\p{Cc}+/gu, " ").trim();
}

function facetValue(raw: string | null) {
  const value = queryText(raw);
  return value === "all" || Array.from(value).length > MAX_FACET_LENGTH ? "" : value;
}

function readFilters(params: URLSearchParams) {
  const sort = SORT_OPTIONS.find(([field]) => field === params.get("sort"))?.[0] ?? "updated";
  const direction = params.get("sort_dir");
  const sortDir = direction === "asc" || direction === "desc" ? direction : defaultDirFor(sort);
  return {
    search: Array.from(queryText(params.get("search"))).slice(0, MAX_SEARCH_LENGTH).join(""),
    org: facetValue(params.get("org")),
    category: facetValue(params.get("category")),
    grade: GRADES.find(([grade]) => grade === params.get("grade"))?.[0] ?? "",
    sort,
    sort_dir: sortDir,
  } as const;
}

function writeFilters(params: URLSearchParams, filters: ReturnType<typeof readFilters>) {
  const next = new URLSearchParams(params);
  const values = {
    ...filters,
    sort: filters.sort === "updated" ? "" : filters.sort,
    sort_dir: filters.sort_dir === defaultDirFor(filters.sort) ? "" : filters.sort_dir,
  };
  for (const [key, value] of Object.entries(values)) {
    if (value) next.set(key, value);
    else next.delete(key);
  }
  return next.toString();
}

const DEFAULT_FILTERS = readFilters(new URLSearchParams());

export default function SkillsPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const navigationType = useNavigationType();
  const params = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const filters = useMemo(() => readFilters(params), [params]);
  const { search, org, category, grade, sort, sort_dir: sortDir } = filters;
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const [viewMode, setViewMode] = useState<"grid" | "grouped">("grid");

  useEffect(() => {
    const canonical = writeFilters(params, filters);
    if (canonical !== params.toString()) {
      void navigate({ search: canonical, hash: location.hash }, { replace: true });
    }
  }, [params, filters, navigate, location.hash]);

  // A history change cancels typing on the old entry. Preserve the caret and
  // trailing space when our own debounced edit is the navigation that finished.
  useLayoutEffect(() => {
    const input = inputRef.current;
    if (input && (navigationType === "POP" || input.value.trim() !== search)) {
      input.value = search;
    }
    return () => clearTimeout(debounceRef.current);
  }, [location.key, navigationType, search]);

  function updateFilters(changes: Partial<typeof filters> = {}) {
    clearTimeout(debounceRef.current);
    const next = writeFilters(params, {
      ...filters,
      search: queryText(inputRef.current?.value ?? search),
      ...changes,
    });
    if (next !== params.toString()) void navigate({ search: next, hash: location.hash });
  }

  function resetFilters() {
    if (inputRef.current) inputRef.current.value = "";
    updateFilters(DEFAULT_FILTERS);
  }

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

  const fetchPage = useCallback(
    (page: number) =>
      listSkillsFiltered({
        page,
        pageSize: PAGE_SIZE,
        search: search || undefined,
        org: org || undefined,
        category: category || undefined,
        grade: grade || undefined,
        sort,
        sortDir,
      }),
    [search, org, category, grade, sort, sortDir],
  );

  const { items, total, loading, loadingMore, error, hasMore, sentinelRef, retry } =
    useInfiniteScroll(fetchPage, [fetchPage]);

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

  const hasCategoryOption = activeCategories.has(category)
    && Object.values(taxonomy?.groups ?? {}).some((group) => group.includes(category));

  return (
    <div className="container">
      <div className={styles.header}>
        <h1 className={styles.title}>
          <Package size={28} />
          Skill Registry
        </h1>
        {(items.length > 0 || (!loading && !error)) && (
          <p className={styles.subtitle}>
            {total} skills — each automatically evaluated and security-graded
          </p>
        )}
      </div>

      {/* Filters bar */}
      <div className={styles.filters}>
        <div className={styles.searchBox}>
          <Search size={16} className={styles.searchIcon} />
          <input
            type="text"
            aria-label="Search skills"
            placeholder="Search skills, e.g. 'Bayesian modeling' or 'time series forecasting'..."
            ref={inputRef}
            defaultValue={search}
            maxLength={MAX_SEARCH_LENGTH}
            onChange={() => {
              clearTimeout(debounceRef.current);
              debounceRef.current = setTimeout(updateFilters, DEBOUNCE_MS);
            }}
            className={styles.searchInput}
          />
        </div>

        <div className={styles.filterGroup}>
          <Filter size={14} />
          <select
            aria-label="Filter by organization"
            value={org}
            onChange={(e) => updateFilters({ org: e.target.value })}
            className={styles.select}
          >
            <option value="">All Orgs</option>
            {org && !orgs.includes(org) && <option value={org}>{org}</option>}
            {orgs.map((org) => (
              <option key={org} value={org}>
                {org}
              </option>
            ))}
          </select>

          <select
            aria-label="Filter by safety grade"
            value={grade}
            onChange={(e) => updateFilters({ grade: e.target.value as typeof grade })}
            className={styles.select}
          >
            <option value="">All Grades</option>
            {GRADES.map(([value, label]) => (
              <option key={value} value={value}>{value} - {label}</option>
            ))}
          </select>

          <select
            aria-label="Filter by category"
            value={category}
            onChange={(e) => updateFilters({ category: e.target.value })}
            className={styles.select}
          >
            <option value="">All Categories</option>
            {category && !hasCategoryOption && <option value={category}>{category}</option>}
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
        </div>

        <div className={styles.sortGroup}>
          <select
            aria-label="Sort skills by"
            value={sort}
            onChange={(e) => {
              const field = e.target.value as SkillSortField;
              updateFilters({ sort: field, sort_dir: defaultDirFor(field) });
            }}
            className={styles.sortSelect}
          >
            {SORT_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>

          <button
            className={styles.sortDirBtn}
            onClick={() => updateFilters({ sort_dir: sortDir === "asc" ? "desc" : "asc" })}
            title={sortDir === "asc" ? "Ascending — click to reverse" : "Descending — click to reverse"}
            aria-label="Toggle sort direction"
          >
            {sortDir === "asc" ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
          </button>

          <button
            className={`${styles.viewToggle} ${viewMode === "grouped" ? styles.viewToggleActive : ""}`}
            onClick={() => setViewMode(viewMode === "grid" ? "grouped" : "grid")}
            title={viewMode === "grid" ? "Group by category" : "Flat grid view"}
          >
            <Layers size={16} />
          </button>
          <button type="button" className={styles.resetBtn} onClick={resetFilters}>
            Reset filters
          </button>
        </div>
      </div>

      {/* Results */}
      {items.length === 0 && loading ? (
        <LoadingSpinner text="Loading skills..." />
      ) : items.length === 0 && error ? (
        <NeonCard glow="pink">
          <p style={{ color: "var(--neon-pink)" }}>Error: {error}</p>
        </NeonCard>
      ) : items.length === 0 ? (
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

          {!skill.source_repo_removed && skill.github_is_archived && (
            <div className={styles.cardArchived}>Archived on GitHub</div>
          )}

          <p className={styles.cardDesc}>{skill.description}</p>

          <div className={styles.cardFooter}>
            <span className={styles.cardVersion}>v{skill.latest_version}</span>
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
      </NeonCard>
    </Link>
  );
}
