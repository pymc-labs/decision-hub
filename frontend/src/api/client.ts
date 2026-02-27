import type {
  SkillSummary,
  OrgProfile,
  PaginatedSkillsResponse,
  ResolveResponse,
  EvalReport,
  PaginatedAuditLogResponse,
  TaxonomyResponse,
  RegistryStats,
  OrgStatsResponse,
  AskResponse,
} from "../types/api";

// When served from Modal (same origin), use "" so fetches are relative.
// For local dev against a remote API, set VITE_API_URL.
const API_BASE = import.meta.env.VITE_API_URL ?? "";

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

export type SkillSortField = "updated" | "name" | "downloads" | "github_stars" | "safety_rating";

export interface SkillsFilterParams {
  page?: number;
  pageSize?: number;
  search?: string;
  org?: string;
  category?: string;
  grade?: string;
  sort?: SkillSortField;
  sortDir?: "asc" | "desc";
}

export async function listSkillsFiltered(
  params: SkillsFilterParams = {}
): Promise<PaginatedSkillsResponse> {
  const qs = new URLSearchParams();
  qs.set("page", String(params.page ?? 1));
  qs.set("page_size", String(params.pageSize ?? 20));
  if (params.search) qs.set("search", params.search);
  if (params.org) qs.set("org", params.org);
  if (params.category) qs.set("category", params.category);
  if (params.grade) qs.set("grade", params.grade);
  if (params.sort) qs.set("sort", params.sort);
  if (params.sortDir) qs.set("sort_dir", params.sortDir);
  return fetchJSON<PaginatedSkillsResponse>(`/v1/skills?${qs.toString()}`);
}

export async function getSkill(
  orgSlug: string,
  skillName: string
): Promise<SkillSummary> {
  return fetchJSON<SkillSummary>(
    `/v1/skills/${orgSlug}/${skillName}/summary`
  );
}

export async function getRegistryStats(): Promise<RegistryStats> {
  return fetchJSON<RegistryStats>("/v1/stats");
}

export type OrgSortField = "slug" | "skill_count" | "total_downloads" | "latest_update";

export async function listOrgStats(params: {
  search?: string;
  typeFilter?: string;
  sort?: OrgSortField;
  sortDir?: "asc" | "desc";
} = {}): Promise<OrgStatsResponse> {
  const qs = new URLSearchParams();
  if (params.search) qs.set("search", params.search);
  if (params.typeFilter) qs.set("type_filter", params.typeFilter);
  if (params.sort) qs.set("sort", params.sort);
  if (params.sortDir) qs.set("sort_dir", params.sortDir);
  return fetchJSON<OrgStatsResponse>(`/v1/orgs/stats?${qs.toString()}`);
}

export async function getOrgProfile(slug: string): Promise<OrgProfile> {
  return fetchJSON<OrgProfile>(`/v1/orgs/${slug}/profile`);
}

export async function listOrgProfiles(): Promise<OrgProfile[]> {
  return fetchJSON<OrgProfile[]>("/v1/orgs/profiles");
}

export async function getTaxonomy(): Promise<TaxonomyResponse> {
  return fetchJSON<TaxonomyResponse>("/v1/taxonomy");
}

export async function resolveSkill(
  orgSlug: string,
  skillName: string,
  spec = "latest",
  allowRisky = false
): Promise<ResolveResponse> {
  return fetchJSON<ResolveResponse>(
    `/v1/resolve/${orgSlug}/${skillName}?spec=${encodeURIComponent(spec)}&allow_risky=${allowRisky}`
  );
}

export async function getEvalReport(
  orgSlug: string,
  skillName: string,
  semver: string
): Promise<EvalReport | null> {
  return fetchJSON<EvalReport | null>(
    `/v1/skills/${orgSlug}/${skillName}/eval-report?semver=${encodeURIComponent(semver)}`
  );
}

export async function getAuditLog(
  orgSlug: string,
  skillName: string,
  semver?: string
): Promise<PaginatedAuditLogResponse> {
  const qs = semver ? `?semver=${encodeURIComponent(semver)}` : "";
  return fetchJSON<PaginatedAuditLogResponse>(
    `/v1/skills/${orgSlug}/${skillName}/audit-log${qs}`
  );
}

export async function askQuestion(query: string): Promise<AskResponse> {
  return fetchJSON<AskResponse>(
    `/v1/ask?q=${encodeURIComponent(query)}`
  );
}

export async function downloadSkillZip(
  orgSlug: string,
  skillName: string,
  spec = "latest",
  allowRisky = false
): Promise<ArrayBuffer> {
  const res = await fetch(
    `${API_BASE}/v1/skills/${orgSlug}/${skillName}/download?spec=${encodeURIComponent(spec)}&allow_risky=${allowRisky}`
  );
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  return res.arrayBuffer();
}
