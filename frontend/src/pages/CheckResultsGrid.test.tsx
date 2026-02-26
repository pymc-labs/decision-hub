import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { CheckResult } from "../types/api";
import { CheckResultsGrid } from "./SkillDetailPage";
import { formatCheckName } from "./auditUtils";

const CHECKS: CheckResult[] = [
  { severity: "pass", check_name: "manifest_schema", message: "Schema is valid" },
  { severity: "fail", check_name: "safety_scan", message: "Found unsafe pattern in code" },
  { severity: "warn", check_name: "dependency_audit", message: "Outdated dependency detected" },
];

describe("formatCheckName", () => {
  it("maps known check names to labels", () => {
    expect(formatCheckName("manifest_schema")).toBe("Manifest Schema");
    expect(formatCheckName("embedded_credentials")).toBe("Credentials Scan");
    expect(formatCheckName("safety_scan")).toBe("Safety Scan");
  });

  it("title-cases unknown check names", () => {
    expect(formatCheckName("some_new_check")).toBe("Some New Check");
  });
});

describe("CheckResultsGrid", () => {
  it("renders all check cards with labels and messages", () => {
    render(<CheckResultsGrid checks={CHECKS} />);

    expect(screen.getByText("Safety Checks")).toBeInTheDocument();
    expect(screen.getByText("Manifest Schema")).toBeInTheDocument();
    expect(screen.getByText("Safety Scan")).toBeInTheDocument();
    expect(screen.getByText("Dependency Audit")).toBeInTheDocument();
    expect(screen.getByText("Schema is valid")).toBeInTheDocument();
    expect(screen.getByText("Found unsafe pattern in code")).toBeInTheDocument();
  });

  it("renders nothing when checks is empty", () => {
    const { container } = render(<CheckResultsGrid checks={[]} />);
    // Grid exists but has no cards
    expect(container.querySelectorAll("[class*=checkCard]")).toHaveLength(0);
  });

  it("handles missing fields gracefully", () => {
    const sparse: CheckResult[] = [
      { severity: undefined, check_name: undefined, message: undefined },
      {},
    ];
    render(<CheckResultsGrid checks={sparse} />);
    // Falls back to "unknown" for check_name -> title-cased
    const labels = screen.getAllByText("Unknown");
    expect(labels).toHaveLength(2);
  });

  it("expands a card message on click and collapses on second click", async () => {
    const user = userEvent.setup();
    render(<CheckResultsGrid checks={CHECKS} />);

    const firstCard = screen.getByText("Schema is valid").closest("[class*=checkCard]")!;
    const messageSpan = screen.getByText("Schema is valid");

    // Initially not expanded
    expect(messageSpan.className).not.toMatch(/checkMessageExpanded/);

    // Click to expand
    await user.click(firstCard);
    expect(messageSpan.className).toMatch(/checkMessageExpanded/);

    // Click again to collapse
    await user.click(firstCard);
    expect(messageSpan.className).not.toMatch(/checkMessageExpanded/);
  });

  it("collapses previous card when a different card is clicked", async () => {
    const user = userEvent.setup();
    render(<CheckResultsGrid checks={CHECKS} />);

    const firstMessage = screen.getByText("Schema is valid");
    const secondMessage = screen.getByText("Found unsafe pattern in code");
    const firstCard = firstMessage.closest("[class*=checkCard]")!;
    const secondCard = secondMessage.closest("[class*=checkCard]")!;

    // Expand first
    await user.click(firstCard);
    expect(firstMessage.className).toMatch(/checkMessageExpanded/);

    // Click second — first collapses, second expands
    await user.click(secondCard);
    expect(firstMessage.className).not.toMatch(/checkMessageExpanded/);
    expect(secondMessage.className).toMatch(/checkMessageExpanded/);
  });
});
