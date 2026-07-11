const CHECK_NAME_LABELS: Record<string, string> = {
  manifest_schema: "Manifest Schema",
  embedded_credentials: "Credentials Scan",
  safety_scan: "Safety Scan",
  prompt_safety: "Prompt Safety",
  pipeline_taint: "Pipeline Taint",
  tool_consistency: "Tool Consistency",
  dependency_audit: "Dependency Audit",
  unscanned_files: "Unscanned Files",
  source_size: "Source Size",
  llm_coverage: "LLM Coverage",
  functional_tests: "Functional Tests",
};

export function formatCheckName(raw: string): string {
  return CHECK_NAME_LABELS[raw] ?? raw.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
