import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import GradeBadge from "./GradeBadge";

describe("GradeBadge", () => {
  it("renders the grade letter for a known grade", () => {
    render(<GradeBadge grade="A" />);
    expect(screen.getByText("A")).toBeDefined();
  });

  it("renders the pending indicator instead of crashing when grade is null", () => {
    // Before the guard, `grade.trim()` on a null value from the API would
    // throw and unmount whatever surrounding SkillCard/detail page was
    // rendering it. Now null falls back to the pending badge.
    render(<GradeBadge grade={null} />);
    expect(screen.getByText("...")).toBeDefined();
  });

  it("renders the pending indicator when grade is undefined", () => {
    render(<GradeBadge grade={undefined} />);
    expect(screen.getByText("...")).toBeDefined();
  });

  it("renders the pending indicator when grade is an empty string", () => {
    render(<GradeBadge grade="" />);
    expect(screen.getByText("...")).toBeDefined();
  });
});
