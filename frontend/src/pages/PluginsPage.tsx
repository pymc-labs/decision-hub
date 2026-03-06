import { useState, useMemo, useEffect, useRef, useCallback } from "react";
import { Link } from "react-router-dom";
import { Search, Puzzle, Filter, User, Tag, ArrowUp, ArrowDown } from "lucide-react";
import { listPluginsFiltered, listOrgProfiles } from "../api/client";
import type { PluginSortField } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useInfiniteScroll } from "../hooks/useInfiniteScroll";
import { useSEO } from "../hooks/useSEO";
import type { PluginSummary } from "../types/api";
import NeonCard from "../components/NeonCard";
import GradeBadge from "../components/GradeBadge";
import LoadingSpinner from "../components/LoadingSpinner";
import styles from "./PluginsPage.module.css";

const PAGE_SIZE = 12;
const DEBOUNCE_MS = 300;

const PLATFORM_OPTIONS = ["All", "Claude", "Cursor", "Codex"];

export default function PluginsPage() {
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [orgFilter, setOrgFilter] = useState<string>("all");
  const [gradeFilter, setGradeFilter] = useState<string>("all");
  const [platformFilter, setPlatformFilter] = useState<string>("all");
  const [sortBy, setSortBy] = useState<PluginSortField>("updated");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const defaultDirFor = (field: PluginSortField): "asc" | "desc" =>
    field === "name" ? "asc" : "desc";

  useSEO({
    title: "Plugins",
    description:
      "Browse the Decision Hub plugin registry. Search and filter AI agent plugins by platform, category, and safety grade.",
    path: "/plugins",
  });

  const { data: orgProfiles } = useApi(() => listOrgProfiles(), []);

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
      listPluginsFiltered({
        page,
        pageSize: PAGE_SIZE,
        search: debouncedSearch || undefined,
        org: orgFilter !== "all" ? orgFilter : undefined,
        platform: platformFilter !== "all" ? platformFilter : undefined,
        grade: gradeFilter !== "all" ? gradeFilter : undefined,
        sort: sortBy,
        sortDir,
      }),
    [debouncedSearch, orgFilter, platformFilter, gradeFilter, sortBy, sortDir],
  );

  const { items, total, loading, loadingMore, error, hasMore, sentinelRef, retry } =
    useInfiniteScroll(fetchPage, [debouncedSearch, orgFilter, platformFilter, gradeFilter, sortBy, sortDir]);

  const orgs = useMemo(
    () => (orgProfiles ?? []).map((p) => p.slug).sort(),
    [orgProfiles],
  );

  if (loading && items.length === 0) return <LoadingSpinner text="Loading plugins..." />;
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
          <Puzzle size={28} />
          Plugin Registry
        </h1>
        <p className={styles.subtitle}>
          {total} plugins — bundled skill packages for AI coding agents
        </p>
      </div>

      {/* Filters bar */}
      <div className={styles.filters}>
        <div className={styles.searchBox}>
          <Search size={16} className={styles.searchIcon} />
          <input
            type="text"
            placeholder="Search plugins..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className={styles.searchInput}
          />
        </div>

        <div className={styles.filterGroup}>
          <Filter size={14} />
          <select
            aria-label="Filter by organization"
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
            aria-label="Filter by platform"
            value={platformFilter}
            onChange={(e) => setPlatformFilter(e.target.value)}
            className={styles.select}
          >
            {PLATFORM_OPTIONS.map((p) => (
              <option key={p} value={p === "All" ? "all" : p.toLowerCase()}>
                {p === "All" ? "All Platforms" : p}
              </option>
            ))}
          </select>

          <select
            aria-label="Filter by safety grade"
            value={gradeFilter}
            onChange={(e) => setGradeFilter(e.target.value)}
            className={styles.select}
          >
            <option value="all">All Grades</option>
            <option value="A">A - Safe</option>
            <option value="B">B - Elevated</option>
            <option value="C">C - Risky</option>
          </select>
        </div>

        <div className={styles.sortGroup}>
          <select
            aria-label="Sort plugins by"
            value={sortBy}
            onChange={(e) => {
              const field = e.target.value as PluginSortField;
              setSortBy(field);
              setSortDir(defaultDirFor(field));
            }}
            className={styles.sortSelect}
          >
            <option value="updated">Latest</option>
            <option value="name">Name</option>
            <option value="downloads">Downloads</option>
            <option value="github_stars">Stars</option>
          </select>

          <button
            className={styles.sortDirBtn}
            onClick={() => setSortDir(sortDir === "asc" ? "desc" : "asc")}
            title={sortDir === "asc" ? "Ascending -- click to reverse" : "Descending -- click to reverse"}
            aria-label="Toggle sort direction"
          >
            {sortDir === "asc" ? <ArrowUp size={14} /> : <ArrowDown size={14} />}
          </button>
        </div>
      </div>

      {/* Results */}
      {items.length === 0 && !loading ? (
        <div className={styles.empty}>
          <Puzzle size={48} />
          <p>No plugins match your filters</p>
        </div>
      ) : (
        <div className={styles.grid}>
          {items.map((plugin) => (
            <PluginCard key={`${plugin.org_slug}/${plugin.plugin_name}`} plugin={plugin} />
          ))}
        </div>
      )}

      {/* Infinite scroll sentinel */}
      {hasMore && (
        <div ref={sentinelRef} className={styles.sentinel}>
          {loadingMore && <span className={styles.loadingMore}>Loading more plugins...</span>}
        </div>
      )}

      {/* Inline error when loading more pages fails */}
      {error && items.length > 0 && (
        <div className={styles.sentinel}>
          <span className={styles.loadMoreError}>Failed to load more plugins.</span>
          <button className={styles.retryBtn} onClick={retry}>Retry</button>
        </div>
      )}
    </div>
  );
}

function PluginCard({ plugin }: { plugin: PluginSummary }) {
  const componentCounts = [
    plugin.skill_count > 0 ? `${plugin.skill_count} skill${plugin.skill_count !== 1 ? "s" : ""}` : null,
    plugin.hook_count > 0 ? `${plugin.hook_count} hook${plugin.hook_count !== 1 ? "s" : ""}` : null,
    plugin.agent_count > 0 ? `${plugin.agent_count} agent${plugin.agent_count !== 1 ? "s" : ""}` : null,
    plugin.command_count > 0 ? `${plugin.command_count} cmd${plugin.command_count !== 1 ? "s" : ""}` : null,
  ].filter(Boolean);

  return (
    <Link
      to={`/plugins/${plugin.org_slug}/${plugin.plugin_name}`}
      className={styles.pluginLink}
    >
      <NeonCard glow="purple">
        <div className={styles.card}>
          <div className={styles.cardTop}>
            <div className={styles.cardOrg}>
              <User size={12} />
              {plugin.org_slug}
            </div>
            <GradeBadge grade={plugin.safety_rating} size="sm" />
          </div>

          <h3 className={styles.cardName}>{plugin.plugin_name}</h3>

          {plugin.platforms.length > 0 && (
            <div className={styles.cardPlatforms}>
              {plugin.platforms.map((p) => (
                <span key={p} className={styles.platformBadge}>{p}</span>
              ))}
            </div>
          )}

          {plugin.category && (
            <div className={styles.cardCategory}>
              <Tag size={10} />
              {plugin.category}
            </div>
          )}

          <p className={styles.cardDesc}>{plugin.description}</p>

          {componentCounts.length > 0 && (
            <div className={styles.cardComponents}>
              {componentCounts.map((c) => (
                <span key={c} className={styles.componentBadge}>{c}</span>
              ))}
            </div>
          )}

          <div className={styles.cardFooter}>
            <span className={styles.cardVersion}>v{plugin.latest_version}</span>
            {plugin.author_name && plugin.author_name !== "auto-sync" && (
              <span className={styles.cardAuthor}>by {plugin.author_name}</span>
            )}
            <span className={styles.cardStats}>
              {plugin.github_stars != null && plugin.github_stars > 0 && (
                <span className={styles.stat}>{plugin.github_stars.toLocaleString()} stars</span>
              )}
              <span className={styles.stat}>{plugin.download_count.toLocaleString()} dl</span>
            </span>
          </div>
        </div>
      </NeonCard>
    </Link>
  );
}
