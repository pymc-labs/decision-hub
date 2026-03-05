import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Card from "./Card";

describe("Card", () => {
  it("renders children", () => {
    render(<Card>Hello</Card>);
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });

  it("applies variant class when provided", () => {
    const { container } = render(<Card variant="elevated">Content</Card>);
    const card = container.firstChild as HTMLElement;
    expect(card.className).toContain("elevated");
  });

  it("applies default variant when none specified", () => {
    const { container } = render(<Card>Content</Card>);
    const card = container.firstChild as HTMLElement;
    expect(card.className).toContain("card");
  });

  it("passes through className prop", () => {
    const { container } = render(<Card className="custom">Content</Card>);
    const card = container.firstChild as HTMLElement;
    expect(card.className).toContain("custom");
  });

  it("passes through onClick prop", async () => {
    let clicked = false;
    render(<Card onClick={() => { clicked = true; }}>Click me</Card>);
    screen.getByText("Click me").click();
    expect(clicked).toBe(true);
  });
});
