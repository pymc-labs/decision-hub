import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { SkillFile } from "../types/api";
import FileBrowser from "./FileBrowser";

const skillA: SkillFile[] = [
  { path: "SKILL.md", content: "# skill A", size: 10 },
  { path: "evals/case_a.json", content: "{}", size: 2 },
  { path: "scripts/run_a.py", content: "print('a')", size: 12 },
];

const skillB: SkillFile[] = [
  { path: "SKILL.md", content: "# skill B", size: 10 },
  { path: "evals/case_b.yaml", content: "case: b", size: 8 },
  { path: "scripts/run_b.py", content: "print('b')", size: 12 },
];

describe("FileBrowser", () => {
  it("renders the SKILL.md content by default", () => {
    render(<FileBrowser files={skillA} />);
    expect(screen.getByText(/skill A/)).toBeDefined();
  });

  it("resets the selected file when navigating to a different skill", () => {
    // Regression: the FileBrowser's default selection is SKILL.md, so
    // switching to a new skill should show the new SKILL.md content, not
    // stale content from the previous skill.
    const { rerender } = render(<FileBrowser files={skillA} />);
    expect(screen.getByText(/skill A/)).toBeDefined();

    rerender(<FileBrowser files={skillB} />);
    expect(screen.getByText(/skill B/)).toBeDefined();
    expect(screen.queryByText(/skill A/)).toBeNull();
  });

  it("does not leak expanded-folder state between different skills", () => {
    // Regression: TreeNodeView holds ``expanded`` in local state and used
    // to be keyed only on ``child.path``. Two skills that share a directory
    // name (like ``evals/``) reused the same node identity and inherited
    // each other's expanded state — meaning a folder collapsed on skill A
    // would appear collapsed on skill B for no user-visible reason (and
    // vice versa). Keying the tree container on a per-files identity
    // forces a full remount so ``expanded`` starts from its default.
    const { rerender, container } = render(<FileBrowser files={skillA} />);

    // Expand a folder that will collide by path with skill B's evals/.
    // At depth<2 folders start expanded, so click to COLLAPSE evals in A.
    const evalsButtonA = screen.getByRole("button", { name: /evals/i });
    fireEvent.click(evalsButtonA);

    // Sanity: the ``evals/case_a.json`` leaf should no longer be visible.
    expect(screen.queryByText("case_a.json")).toBeNull();

    // Now switch to skill B — the collapse state must NOT carry over
    // via the shared "evals" path.
    rerender(<FileBrowser files={skillB} />);

    // The B tree gets a fresh mount, so evals/ starts in its default
    // (expanded) state and case_b.yaml is visible.
    expect(screen.getByText("case_b.yaml")).toBeDefined();

    // Belt-and-braces: the tree container should have re-mounted (new key),
    // which we detect by checking that no A leaf is visible.
    expect(container.querySelector("[class*=tree]")).not.toBeNull();
    expect(screen.queryByText("case_a.json")).toBeNull();
    expect(screen.queryByText("run_a.py")).toBeNull();
  });
});
