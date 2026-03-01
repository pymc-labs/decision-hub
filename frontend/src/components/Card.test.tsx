import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Card from "./Card";

describe("Card", () => {
  it("renders children", () => {
    render(<Card><p>Hello</p></Card>);
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });

  it("applies default variant class when no variant specified", () => {
    const { container } = render(<Card>Content</Card>);
    const card = container.firstChild as HTMLElement;
    expect(card.className).toMatch(/default/);
  });

  it("applies success variant class", () => {
    const { container } = render(<Card variant="success">Content</Card>);
    const card = container.firstChild as HTMLElement;
    expect(card.className).toMatch(/success/);
  });

  it("applies danger variant class", () => {
    const { container } = render(<Card variant="danger">Content</Card>);
    const card = container.firstChild as HTMLElement;
    expect(card.className).toMatch(/danger/);
  });

  it("applies accent variant class", () => {
    const { container } = render(<Card variant="accent">Content</Card>);
    const card = container.firstChild as HTMLElement;
    expect(card.className).toMatch(/accent/);
  });

  it("applies clickable class when onClick is provided", () => {
    const { container } = render(<Card onClick={() => {}}>Content</Card>);
    const card = container.firstChild as HTMLElement;
    expect(card.className).toMatch(/clickable/);
  });

  it("does not apply clickable class when no onClick", () => {
    const { container } = render(<Card>Content</Card>);
    const card = container.firstChild as HTMLElement;
    expect(card.className).not.toMatch(/clickable/);
  });

  it("calls onClick when clicked", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Card onClick={onClick}>Click me</Card>);
    await user.click(screen.getByText("Click me"));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("merges custom className", () => {
    const { container } = render(<Card className="custom-class">Content</Card>);
    const card = container.firstChild as HTMLElement;
    expect(card.className).toContain("custom-class");
  });

  it("applies inline style", () => {
    const { container } = render(<Card style={{ maxWidth: "300px" }}>Content</Card>);
    const card = container.firstChild as HTMLElement;
    expect(card.style.maxWidth).toBe("300px");
  });
});
