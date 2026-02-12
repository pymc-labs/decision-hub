import type {
  SkillSummary,
  OrgProfile,
  PaginatedSkillsResponse,
  ResolveResponse,
  EvalReport,
  AuditLogEntry,
  TaxonomyResponse,
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

export async function listSkills(
  page = 1,
  pageSize = 20
): Promise<PaginatedSkillsResponse> {
  return fetchJSON<PaginatedSkillsResponse>(
    `/v1/skills?page=${page}&page_size=${pageSize}`
  );
}

export async function listAllSkills(): Promise<SkillSummary[]> {
  const first = await listSkills(1, 100);
  const skills = [...first.items];
  for (let p = 2; p <= first.total_pages; p++) {
    const page = await listSkills(p, 100);
    skills.push(...page.items);
  }
  return skills;
}

export async function getOrgProfile(slug: string): Promise<OrgProfile> {
  return fetchJSON<OrgProfile>(`/v1/orgs/${slug}/profile`);
}

export async function getTaxonomy(): Promise<TaxonomyResponse> {
  return fetchJSON<TaxonomyResponse>("/v1/taxonomy");
}

export async function resolveSkill(
  orgSlug: string,
  skillName: string,
  spec = "latest",
  allowRisky = true
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
): Promise<AuditLogEntry[]> {
  const qs = semver ? `?semver=${encodeURIComponent(semver)}` : "";
  return fetchJSON<AuditLogEntry[]>(
    `/v1/skills/${orgSlug}/${skillName}/audit-log${qs}`
  );
}

export async function downloadSkillZip(
  orgSlug: string,
  skillName: string,
  spec = "latest"
): Promise<ArrayBuffer> {
  const res = await fetch(
    `${API_BASE}/v1/skills/${orgSlug}/${skillName}/download?spec=${encodeURIComponent(spec)}`
  );
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  return res.arrayBuffer();
}
