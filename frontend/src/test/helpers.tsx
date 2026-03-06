import { render } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import type {
  SkillSummary,
  EvalReport,
  AuditLogEntry,
  RegistryStats,
  PaginatedSkillsResponse,
} from "../types/api";

/**
 * Render a component inside a MemoryRouter with Routes support.
 * Accepts optional initialEntries and a route path pattern for route params.
 */
export function renderWithRouter(
  ui: React.ReactElement,
  {
    initialEntries = ["/"],
    path = "/",
  }: {
    initialEntries?: string[];
    path?: string;
  } = {},
) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route path={path} element={ui} />
      </Routes>
    </MemoryRouter>,
  );
}

/** Factory for SkillSummary test data. */
export function makeSkill(overrides: Partial<SkillSummary> = {}): SkillSummary {
  return {
    org_slug: "acme",
    skill_name: "test-skill",
    description: "A test skill",
    latest_version: "1.0.0",
    updated_at: "2025-01-01T00:00:00Z",
    safety_rating: "A",
    author: "dev",
    download_count: 10,
    is_personal_org: false,
    category: "",
    source_repo_url: null,
    manifest_path: null,
    source_repo_removed: false,
    github_stars: null,
    github_forks: null,
    github_watchers: null,
    github_is_archived: null,
    github_license: null,
    is_auto_synced: false,
    ...overrides,
  };
}

/** Factory for EvalReport test data. */
export function makeEvalReport(overrides: Partial<EvalReport> = {}): EvalReport {
  return {
    id: "eval-1",
    version_id: "ver-1",
    agent: "claude",
    judge_model: "claude-3-opus",
    case_results: [
      {
        name: "basic-test",
        description: "A basic test case",
        verdict: "pass",
        reasoning: "Test passed successfully",
        agent_output: "Hello world",
        agent_stderr: "",
        exit_code: 0,
        duration_ms: 1500,
        stage: "eval",
      },
    ],
    passed: 1,
    total: 1,
    total_duration_ms: 1500,
    status: "completed",
    error_message: null,
    created_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

/** Factory for AuditLogEntry test data. */
export function makeAuditLogEntry(
  overrides: Partial<AuditLogEntry> = {},
): AuditLogEntry {
  return {
    id: "audit-1",
    org_slug: "acme",
    skill_name: "test-skill",
    semver: "1.0.0",
    grade: "A",
    version_id: "ver-1",
    check_results: [
      {
        severity: "pass",
        check_name: "no_shell_commands",
        message: "No shell commands found",
      },
    ],
    llm_reasoning: null,
    publisher: "dev@example.com",
    quarantine_s3_key: null,
    created_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

/** Factory for RegistryStats test data. */
export function makeRegistryStats(
  overrides: Partial<RegistryStats> = {},
): RegistryStats {
  return {
    total_skills: 42,
    total_orgs: 5,
    total_publishers: 10,
    total_downloads: 1000,
    active_categories: ["Backend & APIs", "AI & LLM", "Data Science & Statistics"],
    ...overrides,
  };
}

/** Factory for PaginatedSkillsResponse test data. */
export function makePaginatedResponse(
  items: SkillSummary[],
  overrides: Partial<Omit<PaginatedSkillsResponse, "items">> = {},
): PaginatedSkillsResponse {
  return {
    items,
    total: items.length,
    page: 1,
    page_size: 20,
    total_pages: 1,
    ...overrides,
  };
}
