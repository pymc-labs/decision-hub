import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Card from "./Card";

describe("Card", () => {
  it("renders children", () => {
    render(<Card>Hello world</Card>);
    expect(screen.getByText("Hello world")).toBeDefined();
  });

  it("applies default accent when none is specified", () => {
    const { container } = render(<Card>Content</Card>);
    const el = container.firstElementChild!;
    expect(el.className).toContain("card");
    expect(el.className).toContain("default");
  });

  it("applies the specified accent class", () => {
    const { container } = render(<Card accent="violet">Content</Card>);
    const el = container.firstElementChild!;
    expect(el.className).toContain("violet");
  });

  it("does not add clickable class or button role without onClick", () => {
    const { container } = render(<Card>Content</Card>);
    const el = container.firstElementChild!;
    expect(el.className).not.toContain("clickable");
    expect(el.getAttribute("role")).toBeNull();
    expect(el.getAttribute("tabindex")).toBeNull();
  });

  it("adds clickable class, button role, and tabIndex when onClick is provided", () => {
    const onClick = vi.fn();
    const { container } = render(<Card onClick={onClick}>Content</Card>);
    const el = container.firstElementChild!;
    expect(el.className).toContain("clickable");
    expect(el.getAttribute("role")).toBe("button");
    expect(el.getAttribute("tabindex")).toBe("0");
  });

  it("calls onClick when clicked", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Card onClick={onClick}>Click me</Card>);

    await user.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("calls onClick on Enter key", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Card onClick={onClick}>Press me</Card>);

    const el = screen.getByRole("button");
    el.focus();
    await user.keyboard("{Enter}");
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("calls onClick on Space key", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Card onClick={onClick}>Press me</Card>);

    const el = screen.getByRole("button");
    el.focus();
    await user.keyboard(" ");
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("merges custom className", () => {
    const { container } = render(<Card className="custom-class">Content</Card>);
    const el = container.firstElementChild!;
    expect(el.className).toContain("custom-class");
  });

  it("passes through style prop", () => {
    const { container } = render(
      <Card style={{ color: "red" }}>Content</Card>
    );
    const el = container.firstElementChild as HTMLElement;
    expect(el.style.color).toBe("red");
  });
});
