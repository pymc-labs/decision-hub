import type {
  SkillSummary,
  OrgProfile,
  PaginatedSkillsResponse,
  ResolveResponse,
  EvalReport,
  PaginatedAuditLogResponse,
  ScanReport,
  TaxonomyResponse,
  RegistryStats,
  OrgStatsResponse,
  AskResponse,
  AskMessage,
  SimilarSkillRef,
} from "../types/api";

// When served from Modal (same origin), use "" so fetches are relative.
// For local dev against a remote API, set VITE_API_URL.
const API_BASE = import.meta.env.VITE_API_URL ?? "";

/**
 * ApiError carries the response status alongside a user-safe message
 * (rendered in the UI) and the raw server body (kept for dev tools and
 * `console.error`, never shown to users).
 */
export class ApiError extends Error {
  readonly status: number;
  readonly body: string;

  constructor(status: number, message: string, body: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

function userFacingMessage(status: number, body: string): string {
  // Try to surface the FastAPI ``detail`` string when it's already a
  // friendly message (e.g. "Skill 'foo' not found"). Anything that looks
  // like a stack trace, hostname, or 500-class server detail gets
  // collapsed to a generic message — we don't want raw internals leaking
  // into the UI.
  if (status === 404) return "Not found.";
  if (status === 401) return "You need to be signed in to do that.";
  if (status === 403) return "You don't have access to this resource.";
  if (status === 429) return "Too many requests — please slow down and try again.";
  if (status >= 500) return "The server is having trouble right now. Please try again shortly.";

  // 4xx other than the ones above: extract `detail` when present, fall
  // back to a generic invalid-request message.
  try {
    const parsed: unknown = JSON.parse(body);
    if (
      parsed &&
      typeof parsed === "object" &&
      "detail" in parsed &&
      typeof (parsed as { detail: unknown }).detail === "string"
    ) {
      return (parsed as { detail: string }).detail;
    }
  } catch {
    // body isn't JSON — fall through
  }
  return "Request failed. Please try again.";
}

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
    // Log the raw body to the console for debugging; throw a sanitised
    // message for the UI so internal hostnames / tracebacks never reach
    // an end user.
    if (res.status >= 500) {
      console.error(`API ${res.status} on ${path}:`, text);
    }
    throw new ApiError(res.status, userFacingMessage(res.status, text), text);
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

export async function getScanReport(
  orgSlug: string,
  skillName: string,
  semver?: string
): Promise<ScanReport | null> {
  const qs = semver ? `?semver=${encodeURIComponent(semver)}` : "";
  return fetchJSON<ScanReport | null>(
    `/v1/skills/${orgSlug}/${skillName}/scan-report${qs}`
  );
}

export async function askQuestionWithHistory(
  query: string,
  history: AskMessage[]
): Promise<AskResponse> {
  return fetchJSON<AskResponse>("/v1/ask", {
    method: "POST",
    body: JSON.stringify({ query, history }),
  });
}

export async function getSimilarSkills(
  orgSlug: string,
  skillName: string
): Promise<SimilarSkillRef[]> {
  return fetchJSON<SimilarSkillRef[]>(
    `/v1/skills/${orgSlug}/${skillName}/similar`
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
