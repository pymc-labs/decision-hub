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

// Default request timeout. Without one, a stalled connection blocks the
// caller forever and the user is stuck on a spinner with no feedback.
const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * Typed error thrown by every API call. Carries the HTTP status so
 * callers can branch on 401/404/etc., a short ``message`` safe to show
 * to a human, and an opaque ``body`` payload (the raw decoded JSON or
 * trimmed text) for callers that want richer detail.
 *
 * Critically, ``message`` never contains raw response HTML — an upstream
 * proxy returning a 5xx error page must not leak its body into the UI.
 */
export class ApiError extends Error {
  public readonly status: number;
  public readonly body: unknown;

  constructor(status: number, message: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/** True when a value smells like a JSON content-type. */
function isJsonContentType(contentType: string | null): boolean {
  if (!contentType) return false;
  return contentType.includes("application/json") || contentType.includes("+json");
}

/** Strip noisy HTML/markup down to a short, displayable error sentence. */
function summarizeNonJsonError(status: number, body: string): string {
  const trimmed = body.trim();
  // Likely an HTML error page (NGINX/Cloudflare/Modal upstream): hide it.
  if (trimmed.startsWith("<")) {
    return `Request failed (${status}).`;
  }
  // Plain text — show at most ~120 chars to avoid sprawling UI.
  const oneline = trimmed.replace(/\s+/g, " ");
  return oneline.length > 120 ? `${oneline.slice(0, 117)}…` : oneline;
}

/** Extract a human message from a parsed JSON error body (FastAPI ``{detail}``). */
function messageFromJsonBody(status: number, body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    // FastAPI validation errors come back as an array; show count only.
    if (Array.isArray(detail)) return `Validation failed (${detail.length} issue${detail.length === 1 ? "" : "s"}).`;
  }
  return `Request failed (${status}).`;
}

async function fetchJSON<T>(
  path: string,
  init?: RequestInit & { timeoutMs?: number },
): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal, ...rest } = init ?? {};

  // Combine caller-supplied AbortSignal with our timeout so either can
  // cancel the request. AbortSignal.timeout() is available in all
  // browsers we target.
  const timeoutSignal = AbortSignal.timeout(timeoutMs);
  const combinedSignal = signal
    ? AbortSignal.any([signal, timeoutSignal])
    : timeoutSignal;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...rest,
      signal: combinedSignal,
      headers: {
        "Content-Type": "application/json",
        ...rest.headers,
      },
    });
  } catch (err) {
    // AbortError covers both manual abort and timeout. Surface a clear
    // dedicated message; otherwise re-raise as a generic network error.
    if (err instanceof DOMException && err.name === "TimeoutError") {
      throw new ApiError(0, `Request timed out after ${timeoutMs}ms.`);
    }
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new ApiError(0, "Request was aborted.");
    }
    const reason = err instanceof Error ? err.message : "Network error";
    throw new ApiError(0, reason);
  }

  if (!res.ok) {
    const contentType = res.headers.get("content-type");
    if (isJsonContentType(contentType)) {
      let body: unknown = null;
      try {
        body = await res.json();
      } catch {
        // fall through to the text path
      }
      if (body !== null) {
        throw new ApiError(res.status, messageFromJsonBody(res.status, body), body);
      }
    }
    const text = await res.text();
    throw new ApiError(res.status, summarizeNonJsonError(res.status, text), text);
  }
  return res.json() as Promise<T>;
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
  allowRisky = false,
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<ArrayBuffer> {
  const url =
    `${API_BASE}/v1/skills/${orgSlug}/${skillName}/download` +
    `?spec=${encodeURIComponent(spec)}&allow_risky=${allowRisky}`;
  let res: Response;
  try {
    res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
  } catch (err) {
    if (err instanceof DOMException && err.name === "TimeoutError") {
      throw new ApiError(0, `Download timed out after ${timeoutMs}ms.`);
    }
    const reason = err instanceof Error ? err.message : "Network error";
    throw new ApiError(0, reason);
  }
  if (!res.ok) {
    throw new ApiError(res.status, `Download failed (${res.status}).`);
  }
  return res.arrayBuffer();
}
