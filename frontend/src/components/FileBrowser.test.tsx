import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import FileBrowser from "./FileBrowser";

function file(path: string, content: string) {
  return { path, content, size: content.length };
}

const nested = file("Docs/API/Examples/Guide.txt", "Nested guide");
const archive = [
  nested,
  file("Docs/Guide.txt", "Top-level guide"),
  file("SKILL.md", "Manifest"),
];

describe("FileBrowser finder", () => {
  it("opens a collapsed file by a case-insensitive substring spanning path segments", async () => {
    const user = userEvent.setup();
    render(<FileBrowser files={archive} />);
    expect(screen.getByRole("button", { name: "Examples" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getAllByRole("button", { name: "Guide.txt" })).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Docs" }));
    await user.click(screen.getByRole("searchbox", { name: /filter files/i }));
    await user.keyboard("Pi/eXam");
    expect(screen.queryByRole("button", { name: "Docs/Guide.txt" })).toBeNull();
    expect(screen.queryByRole("button", { name: "SKILL.md" })).toBeNull();
    const result = screen.getByRole("button", { name: nested.path });
    await user.tab(); // Clear filter
    await user.tab();
    expect(result).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(result).toHaveAttribute("aria-current", "true");
    expect(screen.getByText(nested.content)).toBeVisible();

    await user.click(screen.getByRole("button", { name: /clear filter/i }));
    expect(screen.getByRole("searchbox")).toHaveFocus();
    expect(screen.getByRole("button", { name: "Docs" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText(nested.content)).toBeVisible();
  });

  it("distinguishes equal filenames and announces empty results without closing the preview", async () => {
    const user = userEvent.setup();
    render(<FileBrowser files={archive} />);
    const input = screen.getByRole("searchbox", { name: /filter files/i });
    await user.type(input, "iDe.T");
    expect(screen.getByRole("status")).toHaveTextContent("2 matching files");
    expect(screen.getByRole("button", { name: nested.path })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Docs/Guide.txt" }));
    expect(screen.getByText("Top-level guide")).toBeVisible();

    await user.type(input, "x-more");
    expect(screen.getByRole("status")).toHaveTextContent(/no matching files/i);
    expect(screen.queryByRole("button", { name: /Guide\.txt/ })).toBeNull();
    expect(screen.getByText("Top-level guide")).toBeVisible();
    await user.clear(input);
    expect(screen.getByRole("button", { name: "Guide.txt" })).toHaveAttribute("aria-current", "true");
  });

  it("resets the filter, selection and folders when another archive has overlapping paths", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<FileBrowser files={archive} />);
    await user.click(screen.getByRole("button", { name: "Docs" }));
    await user.type(screen.getByRole("searchbox"), "examples");
    await user.click(screen.getByRole("button", { name: nested.path }));

    rerender(<FileBrowser files={[file("Docs/Guide.txt", "Other guide"), file("SKILL.md", "New manifest")]} />);
    expect(screen.getByRole("searchbox")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Guide.txt" })).toBeVisible();
    expect(screen.getByRole("button", { name: "SKILL.md" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByText("New manifest")).toBeVisible();
    expect(screen.queryByText(nested.content)).toBeNull();
  });
});
