// API response types matching the FastAPI backend schemas

export interface SkillSummary {
  org_slug: string;
  skill_name: string;
  description: string;
  latest_version: string;
  updated_at: string;
  safety_rating: string;
  author: string;
  download_count: number;
  is_personal_org: boolean;
  category: string;
  source_repo_url: string | null;
  manifest_path: string | null;
  source_repo_removed: boolean;
  github_stars: number | null;
  github_forks: number | null;
  github_watchers: number | null;
  github_is_archived: boolean | null;
  github_license: string | null;
  is_auto_synced: boolean;
}

export interface PaginatedSkillsResponse {
  items: SkillSummary[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface OrgSummary {
  id: string;
  slug: string;
}

export interface OrgProfile {
  slug: string;
  is_personal: boolean;
  avatar_url: string | null;
  description: string | null;
  blog: string | null;
}

export interface ResolveResponse {
  version: string;
  download_url: string;
  checksum: string;
}

export interface EvalCaseResult {
  name: string;
  description: string;
  verdict: string;
  reasoning: string;
  agent_output: string;
  agent_stderr: string;
  exit_code: number;
  duration_ms: number;
  stage: string;
}

export interface EvalReport {
  id: string;
  version_id: string;
  agent: string;
  judge_model: string;
  case_results: EvalCaseResult[];
  passed: number;
  total: number;
  total_duration_ms: number;
  status: string;
  error_message: string | null;
  created_at: string | null;
}

export interface CheckResult {
  severity?: string;
  check_name?: string;
  message?: string;
  [key: string]: unknown;
}

export interface AuditLogEntry {
  id: string;
  org_slug: string;
  skill_name: string;
  semver: string;
  grade: string;
  version_id: string | null;
  check_results: CheckResult[];
  llm_reasoning: Record<string, unknown> | null;
  publisher: string;
  quarantine_s3_key: string | null;
  created_at: string | null;
}

export interface PaginatedAuditLogResponse {
  items: AuditLogEntry[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface ScanFinding {
  rule_id: string;
  category: string;
  severity: string;
  title: string;
  description: string | null;
  file_path: string | null;
  line_number: number | null;
  snippet: string | null;
  remediation: string | null;
  analyzer: string | null;
  is_false_positive: boolean | null;
  meta_confidence: string | null;
  meta_priority: number | null;
  meta_impact: string | null;
  meta_exploitability: string | null;
  meta_confidence_reason: string | null;
  metadata: Record<string, unknown>;
}

export interface ScanReport {
  id: string;
  version_id: string | null;
  is_safe: boolean;
  max_severity: string;
  findings_count: number;
  findings: ScanFinding[];
  analyzers_used: string[];
  analyzers_failed: { analyzer: string; error: string }[];
  analyzability_score: number | null;
  meta_verdict: string | null;
  meta_risk_level: string | null;
  meta_summary: string | null;
  meta_top_priority: string | null;
  meta_verdict_reasoning: string | null;
  meta_correlations: Record<string, unknown>[] | null;
  meta_recommendations: Record<string, unknown>[] | null;
  meta_false_positive_count: number | null;
  llm_overall_assessment: string | null;
  llm_primary_threats: string[] | null;
  scanner_version: string | null;
  scanner_model: string | null;
  policy_name: string | null;
  scan_duration_ms: number | null;
  full_report: Record<string, unknown> | null;
  created_at: string | null;
  scanned_semver: string | null;
  latest_semver: string | null;
}

export interface SkillFile {
  path: string;
  content: string;
  size: number;
}

export interface TaxonomyResponse {
  groups: Record<string, string[]>;
}

export interface RegistryStats {
  total_skills: number;
  total_orgs: number;
  total_publishers: number;
  total_downloads: number;
  active_categories: string[];
}

export interface OrgStatsEntry {
  slug: string;
  is_personal: boolean;
  avatar_url: string | null;
  skill_count: number;
  total_downloads: number;
  latest_update: string | null;
}

export interface OrgStatsResponse {
  items: OrgStatsEntry[];
}

export interface SimilarSkillRef {
  org_slug: string;
  skill_name: string;
  description: string;
  safety_rating: string;
  category: string;
  download_count: number;
}

export interface AskSkillRef {
  org_slug: string;
  skill_name: string;
  description: string;
  safety_rating: string;
  reason: string;
  author: string;
  category: string;
  download_count: number;
  latest_version: string;
  source_repo_url: string | null;
  gauntlet_summary: string | null;
  github_stars: number | null;
  github_license: string | null;
}

export interface AskResponse {
  query: string;
  answer: string;
  skills: AskSkillRef[];
  category: string | null;
}

export interface AskMessage {
  role: "user" | "assistant";
  content: string;
}
