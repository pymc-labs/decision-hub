import type { SkillSummary } from "../types/api";

export interface OrgInfo {
  slug: string;
  skillCount: number;
  totalDownloads: number;
  latestUpdate: string;
  isPersonal: boolean;
}

/** Extract unique sorted org slugs from skills. */
export function extractOrgs(skills: SkillSummary[]): string[] {
  return [...new Set(skills.map((s) => s.org_slug))].sort();
}

/** Filter and sort skills by search, org, grade, and sort order. */
export function filterSkills(
  skills: SkillSummary[],
  search: string,
  orgFilter: string,
  gradeFilter: string,
  sortBy: string,
): SkillSummary[] {
  let result = [...skills];

  if (search) {
    const q = search.toLowerCase();
    result = result.filter(
      (s) =>
        s.skill_name.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q) ||
        s.org_slug.toLowerCase().includes(q),
    );
  }

  if (orgFilter !== "all") {
    result = result.filter((s) => s.org_slug === orgFilter);
  }

  if (gradeFilter !== "all") {
    result = result.filter((s) =>
      s.safety_rating.trim().startsWith(gradeFilter),
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
}

/** Aggregate skills into org summaries, sorted alphabetically. */
export function aggregateOrgs(skills: SkillSummary[]): OrgInfo[] {
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
}

/** Filter orgs by search text and type (orgs/users/all). */
export function filterOrgs(
  orgs: OrgInfo[],
  search: string,
  typeFilter: string,
): OrgInfo[] {
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
}
