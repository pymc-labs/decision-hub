import { useState, useMemo, useCallback } from "react";
import { Link } from "react-router-dom";
import { Search, Package, Download, Filter, User, ChevronLeft, ChevronRight } from "lucide-react";
import { listSkills } from "../api/client";
import { useApi } from "../hooks/useApi";
import NeonCard from "../components/NeonCard";
import GradeBadge from "../components/GradeBadge";
import LoadingSpinner from "../components/LoadingSpinner";
import styles from "./SkillsPage.module.css";

const PAGE_SIZE = 12;

export default function SkillsPage() {
  const [page, setPage] = useState(1);
  const { data, loading, error } = useApi(
    () => listSkills(page, PAGE_SIZE),
    [page]
  );

  const skills = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = data?.total_pages ?? 1;

  const [search, setSearch] = useState("");
  const [orgFilter, setOrgFilter] = useState<string>("all");
  const [gradeFilter, setGradeFilter] = useState<string>("all");
  const [sortBy, setSortBy] = useState<"name" | "downloads" | "updated">("updated");

  const orgs = useMemo(() => {
    return [...new Set(skills.map((s) => s.org_slug))].sort();
  }, [skills]);

  const filtered = useMemo(() => {
    let result = [...skills];

    if (search) {
      const q = search.toLowerCase();
      result = result.filter(
        (s) =>
          s.skill_name.toLowerCase().includes(q) ||
          s.description.toLowerCase().includes(q) ||
          s.org_slug.toLowerCase().includes(q)
      );
    }

    if (orgFilter !== "all") {
      result = result.filter((s) => s.org_slug === orgFilter);
    }

    if (gradeFilter !== "all") {
      result = result.filter((s) =>
        s.safety_rating.trim().startsWith(gradeFilter)
      );
    }

    if (sortBy === "name") {
      result.sort((a, b) => a.skill_name.localeCompare(b.skill_name));
    } else if (sortBy === "downloads") {
      result.sort((a, b) => b.download_count - a.download_count);
    } else {
      result.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    }

    return result;
  }, [skills, search, orgFilter, gradeFilter, sortBy]);

  const goToPage = useCallback((p: number) => {
    setPage(Math.max(1, Math.min(p, totalPages)));
  }, [totalPages]);

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
          {total} skills published across {orgs.length} organizations
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
            onChange={(e) => setSearch(e.target.value)}
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
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as "name" | "downloads" | "updated")}
            className={styles.select}
          >
            <option value="updated">Latest</option>
            <option value="name">Name</option>
            <option value="downloads">Downloads</option>
          </select>
        </div>
      </div>

      {/* Results */}
      {filtered.length === 0 ? (
        <div className={styles.empty}>
          <Package size={48} />
          <p>No skills match your filters</p>
        </div>
      ) : (
        <div className={styles.grid}>
          {filtered.map((skill) => (
            <Link
              key={`${skill.org_slug}/${skill.skill_name}`}
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
          ))}
        </div>
      )}

      {/* Pagination controls */}
      {totalPages > 1 && (
        <div className={styles.pagination}>
          <button
            className={styles.pageButton}
            onClick={() => goToPage(page - 1)}
            disabled={page <= 1}
          >
            <ChevronLeft size={16} />
            Prev
          </button>
          <span className={styles.pageInfo}>
            Page {page} of {totalPages}
          </span>
          <button
            className={styles.pageButton}
            onClick={() => goToPage(page + 1)}
            disabled={page >= totalPages}
          >
            Next
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
