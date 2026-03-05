import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import GradeBadge from "./GradeBadge";

describe("GradeBadge", () => {
  it("renders grade letter", () => {
    render(<GradeBadge grade="A" />);
    expect(screen.getByText("A")).toBeInTheDocument();
  });

  it("applies olive class for grade A", () => {
    const { container } = render(<GradeBadge grade="A" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain("olive");
  });

  it("applies charcoal class for grade B", () => {
    const { container } = render(<GradeBadge grade="B" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain("charcoal");
  });

  it("applies terracotta class for grade C", () => {
    const { container } = render(<GradeBadge grade="C" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain("terracotta");
  });

  it("applies destructive class for grade F", () => {
    const { container } = render(<GradeBadge grade="F" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain("destructive");
  });

  it("applies muted class for pending grade", () => {
    const { container } = render(<GradeBadge grade="pending" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain("muted");
  });

  it("renders tooltip", () => {
    render(<GradeBadge grade="A" />);
    const badge = screen.getByText("A");
    expect(badge.getAttribute("title")).toContain("Safe");
  });

  it("supports size prop", () => {
    const { container } = render(<GradeBadge grade="A" size="lg" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain("lg");
  });
});
