import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import FileBrowser from "./FileBrowser";

describe("FileBrowser", () => {
  it("renders without crashing with empty files", () => {
    const { container } = render(<FileBrowser files={[]} />);
    expect(container).toBeInTheDocument();
  });

  it("renders file tree when files provided", () => {
    const files = [
      { path: "SKILL.md", content: "# Test", size: 6 },
      { path: "src/main.py", content: "print('hi')", size: 11 },
    ];
    const { container } = render(<FileBrowser files={files} />);
    expect(container.querySelector("[class*='browser']")).toBeInTheDocument();
  });
});
