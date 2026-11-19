import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { makeEvalReport } from "../test/helpers";
import EvalReportView from "./EvalReportView";

const passed = { ...makeEvalReport().case_results[0], stage: "judge" };
const failed = {
  ...passed,
  name: "wrong-answer",
  verdict: "fail",
  reasoning: "Wrong answer",
};
const judgeError = {
  ...passed,
  name: "judge-timeout",
  verdict: "error",
  reasoning: "Judge timed out",
};
const agentError = {
  ...passed,
  name: "agent-exit",
  verdict: "error",
  stage: "agent",
  reasoning: "Agent exited",
  agent_stderr: "Missing input",
  exit_code: 1,
};
const report = makeEvalReport({
  case_results: [judgeError, passed, failed, agentError],
  passed: 1,
  total: 4,
  status: "failed",
});

function visibleCaseNames() {
  return screen.queryAllByRole("heading", { level: 4 }).map((heading) => heading.textContent);
}

describe("EvalReportView", () => {
  it("filters by the recorded verdict, preserves case order and keeps the whole-report score", async () => {
    const user = userEvent.setup();
    render(<EvalReportView report={report} />);

    const all = screen.getByRole("radio", { name: "All (4)" });
    expect(screen.getByRole("group", { name: "Filter cases by verdict" })).toContainElement(all);
    expect(all).toBeChecked();
    const names = report.case_results.map((result) => result.name);
    expect(visibleCaseNames()).toEqual(names);

    await user.tab();
    expect(all).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("radio", { name: "Passed (1)" })).toBeChecked();
    expect(visibleCaseNames()).toEqual([passed.name]);

    await user.click(screen.getByRole("radio", { name: "Failed (1)" }));
    expect(visibleCaseNames()).toEqual([failed.name]);
    expect(screen.getByText("Wrong answer")).toBeVisible();

    await user.click(screen.getByRole("radio", { name: "Errors (2)" }));
    expect(visibleCaseNames()).toEqual([judgeError.name, agentError.name]);
    expect(screen.getByText("Judge timed out")).toBeVisible();
    expect(screen.getByText("Missing input")).toBeVisible();
    expect(screen.getByText("1").parentElement).toHaveTextContent("1/4");
    expect(screen.getByText("failed")).toBeVisible();

    await user.click(all);
    expect(visibleCaseNames()).toEqual(names);
  });

  it("explains a filter with no matches and lets the user return to all cases", async () => {
    const user = userEvent.setup();
    render(<EvalReportView report={makeEvalReport()} />);

    await user.click(screen.getByRole("radio", { name: "Failed (0)" }));
    expect(visibleCaseNames()).toEqual([]);
    expect(screen.getByRole("status")).toHaveTextContent("No cases match this verdict.");

    await user.click(screen.getByRole("radio", { name: "All (1)" }));
    expect(visibleCaseNames()).toEqual([passed.name]);
    expect(screen.queryByText("No cases match this verdict.")).toBeNull();
  });

  it("preserves the selection on refresh and resets it when another report opens", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<EvalReportView report={report} />);
    await user.click(screen.getByRole("radio", { name: "Failed (1)" }));

    rerender(<EvalReportView report={{ ...report }} />);
    expect(visibleCaseNames()).toEqual([failed.name]);

    const next = makeEvalReport({ id: "another-run" });
    rerender(<EvalReportView report={next} />);
    expect(screen.getByRole("radio", { name: "All (1)" })).toBeChecked();
    expect(visibleCaseNames()).toEqual([passed.name]);
  });

  it("filters cases independently when multiple cases have the same name", async () => {
    const user = userEvent.setup();
    const repeated = {
      ...report,
      case_results: [passed, failed, { ...judgeError, name: failed.name }, agentError],
    };
    render(<EvalReportView report={repeated} />);

    await user.click(screen.getByRole("radio", { name: "Errors (2)" }));
    expect(visibleCaseNames()).toEqual([failed.name, agentError.name]);
    expect(screen.queryByText("Wrong answer")).toBeNull();
    expect(screen.getByText("Judge timed out")).toBeVisible();
  });

  it("shows the report error and a distinct empty state when there are no results to filter", () => {
    const empty = makeEvalReport({
      passed: 0,
      total: 0,
      case_results: [],
      status: "error",
      error_message: "Run interrupted",
    });
    render(<EvalReportView report={empty} />);

    expect(screen.getByText("Run interrupted")).toBeVisible();
    expect(screen.getByText("This report has no case results.")).toBeVisible();
    expect(screen.queryByRole("radio")).toBeNull();
  });
});
