import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import EvalReportView from "./EvalReportView";
import type { EvalReport } from "../types/api";

describe("EvalReportView", () => {
  it("renders without crashing with minimal report data", () => {
    const report: EvalReport = {
      id: "test-id",
      version_id: "v1",
      agent: "claude",
      judge_model: "gpt-4",
      case_results: [],
      passed: 0,
      total: 0,
      total_duration_ms: 0,
      status: "completed",
      error_message: null,
      created_at: null,
    };
    const { container } = render(<EvalReportView report={report} />);
    expect(container).toBeInTheDocument();
  });
});
