import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { Search, Package, Download, Filter, User, Tag, Layers, ChevronLeft, ChevronRight } from "lucide-react";
import { listAllSkills, getTaxonomy } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { SkillSummary } from "../types/api";
import { extractOrgs, filterSkills } from "../lib/filters";
import NeonCard from "../components/NeonCard";
import GradeBadge from "../components/GradeBadge";
import LoadingSpinner from "../components/LoadingSpinner";
import styles from "./SkillsPage.module.css";

const PAGE_SIZE = 12;

export default function SkillsPage() {
  const [page, setPage] = useState(1);
  const { data: allSkills, loading, error } = useApi(() => listAllSkills(), []);
  const { data: taxonomy } = useApi(() => getTaxonomy(), []);
  const [search, setSearch] = useState("");
  const [orgFilter, setOrgFilter] = useState<string>("all");
  const [gradeFilter, setGradeFilter] = useState<string>("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [sortBy, setSortBy] = useState<"name" | "downloads" | "updated">("updated");
  const [viewMode, setViewMode] = useState<"grid" | "grouped">("grid");

  const skills = allSkills ?? [];

  const orgs = useMemo(
    () => extractOrgs(skills),
    [skills],
  );

  const activeCategories = useMemo(() => {
    return new Set(skills.map((s) => s.category).filter(Boolean));
  }, [skills]);

  // Filter the full dataset, then paginate the result
  const filtered = useMemo(
    () => filterSkills(skills, search, orgFilter, gradeFilter, sortBy, categoryFilter),
    [skills, search, orgFilter, gradeFilter, sortBy, categoryFilter],
  );

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paginatedSkills = useMemo(
    () => filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE),
    [filtered, page],
  );

  const groupedSkills = useMemo(() => {
    const groups: Record<string, SkillSummary[]> = {};
    for (const skill of paginatedSkills) {
      const cat = skill.category || "Uncategorized";
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(skill);
    }
    return groups;
  }, [paginatedSkills]);

  // Reset to page 1 when filters change
  const resetAndSetSearch = (v: string) => { setSearch(v); setPage(1); };
  const resetAndSetOrg = (v: string) => { setOrgFilter(v); setPage(1); };
  const resetAndSetGrade = (v: string) => { setGradeFilter(v); setPage(1); };
  const resetAndSetCategory = (v: string) => { setCategoryFilter(v); setPage(1); };
  const resetAndSetSort = (v: "name" | "downloads" | "updated") => { setSortBy(v); setPage(1); };

  if (loading) return <LoadingSpinner text="Loading skills..." />;
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
          <Package size={28} />
          Skill Registry
        </h1>
        <p className={styles.subtitle}>
          {skills.length} skills published across {orgs.length} organizations
        </p>
      </div>

      {/* Filters bar */}
      <div className={styles.filters}>
        <div className={styles.searchBox}>
          <Search size={16} className={styles.searchIcon} />
          <input
            type="text"
            placeholder="Search skills..."
            value={search}
            onChange={(e) => resetAndSetSearch(e.target.value)}
            className={styles.searchInput}
          />
        </div>

        <div className={styles.filterGroup}>
          <Filter size={14} />
          <select
            value={orgFilter}
            onChange={(e) => resetAndSetOrg(e.target.value)}
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
            onChange={(e) => resetAndSetGrade(e.target.value)}
            className={styles.select}
          >
            <option value="all">All Grades</option>
            <option value="A">A - Safe</option>
            <option value="B">B - Elevated</option>
            <option value="C">C - Risky</option>
          </select>

          <select
            value={categoryFilter}
            onChange={(e) => resetAndSetCategory(e.target.value)}
            className={styles.select}
          >
            <option value="all">All Categories</option>
            {Object.entries(taxonomy?.groups ?? {}).map(([group, subcategories]) => {
              const activeSubs = subcategories.filter((sub) =>
                activeCategories.has(sub)
              );
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
            onChange={(e) => resetAndSetSort(e.target.value as "name" | "downloads" | "updated")}
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
      {paginatedSkills.length === 0 ? (
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
          {paginatedSkills.map((skill) => (
            <SkillCard key={`${skill.org_slug}/${skill.skill_name}`} skill={skill} />
          ))}
        </div>
      )}

      {/* Pagination */}
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
