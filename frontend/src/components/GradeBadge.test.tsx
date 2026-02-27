import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import GradeBadge from "./GradeBadge";

describe("GradeBadge", () => {
  it("renders grade A with correct label and tooltip", () => {
    render(<GradeBadge grade="A" />);
    const badge = screen.getByText("A");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("title", expect.stringContaining("Safe"));
  });

  it("renders grade F with correct label and tooltip", () => {
    render(<GradeBadge grade="F" />);
    const badge = screen.getByText("F");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("title", expect.stringContaining("Unsafe"));
  });

  it("renders pending grade", () => {
    render(<GradeBadge grade="pending" />);
    expect(screen.getByText("...")).toBeInTheDocument();
  });

  it("handles formatted grade strings like 'A  Safe'", () => {
    render(<GradeBadge grade="A  Safe" />);
    const badge = screen.getByText("A");
    expect(badge).toBeInTheDocument();
  });

  it("applies size CSS class", () => {
    const { container } = render(<GradeBadge grade="B" size="lg" />);
    const badge = container.querySelector("span");
    expect(badge?.className).toMatch(/lg/);
  });

  it("applies color CSS class based on grade", () => {
    const { container } = render(<GradeBadge grade="A" />);
    const badge = container.querySelector("span");
    expect(badge?.className).toMatch(/green/);
  });

  it("falls back for unknown grade", () => {
    render(<GradeBadge grade="Z" />);
    const badge = screen.getByText("Z");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("title", "Unknown grade");
  });

  it("defaults to md size when size is not provided", () => {
    const { container } = render(<GradeBadge grade="A" />);
    const badge = container.querySelector("span");
    expect(badge?.className).toMatch(/md/);
  });
});
