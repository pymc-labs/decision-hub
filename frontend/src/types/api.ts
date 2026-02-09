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
}

export interface OrgSummary {
  id: string;
  slug: string;
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

export interface AuditLogEntry {
  id: string;
  org_slug: string;
  skill_name: string;
  semver: string;
  grade: string;
  version_id: string | null;
  check_results: Record<string, unknown>[];
  llm_reasoning: Record<string, unknown> | null;
  publisher: string;
  quarantine_s3_key: string | null;
  created_at: string | null;
}

export interface SkillFile {
  path: string;
  content: string;
  size: number;
}
