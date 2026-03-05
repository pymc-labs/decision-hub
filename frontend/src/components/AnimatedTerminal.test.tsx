import { render } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";
import AnimatedTerminal from "./AnimatedTerminal";

beforeAll(() => {
  // jsdom does not implement IntersectionObserver
  global.IntersectionObserver = vi.fn().mockImplementation(() => ({
    observe: vi.fn(),
    unobserve: vi.fn(),
    disconnect: vi.fn(),
  }));
});

describe("AnimatedTerminal", () => {
  it("renders the terminal container", () => {
    const { container } = render(<AnimatedTerminal />);
    expect(container.querySelector("[class*='terminal']")).toBeInTheDocument();
  });

  it("renders terminal header dots", () => {
    const { container } = render(<AnimatedTerminal />);
    const dots = container.querySelectorAll("[class*='dot']");
    expect(dots.length).toBe(3);
  });
});
