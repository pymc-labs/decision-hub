import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { SkillSummary } from "../types/api";
import SkillsPage from "./SkillsPage";

function makeSkill(overrides: Partial<SkillSummary> = {}): SkillSummary {
  return {
    org_slug: "acme",
    skill_name: "test-skill",
    description: "A test skill",
    latest_version: "1.0.0",
    updated_at: "2025-01-01T00:00:00Z",
    safety_rating: "A",
    author: "dev",
    download_count: 10,
    is_personal_org: false,
    category: "",
    ...overrides,
  };
}

const SKILLS: SkillSummary[] = [
  makeSkill({
    skill_name: "api-gen",
    description: "Generates APIs",
    category: "Backend & APIs",
    download_count: 100,
    updated_at: "2025-03-01T00:00:00Z",
  }),
  makeSkill({
    skill_name: "llm-tool",
    description: "LLM helper",
    category: "AI & LLM",
    download_count: 50,
    updated_at: "2025-02-01T00:00:00Z",
  }),
  makeSkill({
    skill_name: "css-fix",
    description: "Fixes CSS",
    category: "Frontend & UI",
    download_count: 20,
    updated_at: "2025-01-01T00:00:00Z",
  }),
];

const TAXONOMY = {
  groups: {
    Development: ["Backend & APIs", "Frontend & UI", "Mobile Development", "Programming Languages"],
    "AI & Automation": ["AI & LLM", "Agents & Orchestration", "Prompts & Instructions"],
  },
};

const server = setupServer(
  http.get("/v1/skills", () =>
    HttpResponse.json({
      items: SKILLS,
      total: SKILLS.length,
      page: 1,
      page_size: 100,
      total_pages: 1,
    }),
  ),
  http.get("/v1/taxonomy", () => HttpResponse.json(TAXONOMY)),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPage() {
  return render(
    <MemoryRouter>
      <SkillsPage />
    </MemoryRouter>,
  );
}

/** Wait for the skill grid to load (first skill name visible). */
async function waitForSkills() {
  await screen.findByText("api-gen");
}

/** Get the category <select> by finding the one with "All Categories". */
function getCategorySelect(): HTMLSelectElement {
  const selects = screen.getAllByRole("combobox") as HTMLSelectElement[];
  const match = selects.find((s) =>
    Array.from(s.options).some((o) => o.textContent === "All Categories"),
  );
  if (!match) throw new Error("Category select not found");
  return match;
}

describe("SkillsPage", () => {
  it("renders all skills after loading", async () => {
    renderPage();
    await waitForSkills();
    expect(screen.getByText("api-gen")).toBeInTheDocument();
    expect(screen.getByText("llm-tool")).toBeInTheDocument();
    expect(screen.getByText("css-fix")).toBeInTheDocument();
  });

  it("shows category badges on skill cards", async () => {
    renderPage();
    await waitForSkills();
    // Cards are links — look inside them for the category badge class
    const links = screen.getAllByRole("link");
    const cardTexts = links.map((link) => link.textContent);
    expect(cardTexts.some((t) => t?.includes("Backend & APIs"))).toBe(true);
    expect(cardTexts.some((t) => t?.includes("AI & LLM"))).toBe(true);
    expect(cardTexts.some((t) => t?.includes("Frontend & UI"))).toBe(true);
  });

  it("has a category dropdown with grouped options", async () => {
    renderPage();
    await waitForSkills();
    const select = getCategorySelect();
    // Should contain optgroups for active categories
    const optgroups = select.querySelectorAll("optgroup");
    expect(optgroups.length).toBeGreaterThan(0);
    // "All Categories" should be the default
    expect(select.value).toBe("all");
  });

  it("filters skills by category selection", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForSkills();

    const select = getCategorySelect();
    await user.selectOptions(select, "Backend & APIs");

    // Only "api-gen" should remain
    expect(screen.getByText("api-gen")).toBeInTheDocument();
    expect(screen.queryByText("llm-tool")).not.toBeInTheDocument();
    expect(screen.queryByText("css-fix")).not.toBeInTheDocument();
  });

  it("shows grouped view when toggle is clicked", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForSkills();

    const toggleButton = screen.getByTitle("Group by category");
    await user.click(toggleButton);

    // In grouped view, category names appear as section headings (h2)
    const headings = screen.getAllByRole("heading", { level: 2 });
    const headingTexts = headings.map((h) => h.textContent);
    expect(headingTexts.some((t) => t?.includes("Backend & APIs"))).toBe(true);
    expect(headingTexts.some((t) => t?.includes("AI & LLM"))).toBe(true);
  });

  it("toggles back to flat grid view", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForSkills();

    const toggleButton = screen.getByTitle("Group by category");
    await user.click(toggleButton);
    expect(screen.getByTitle("Flat grid view")).toBeInTheDocument();

    await user.click(screen.getByTitle("Flat grid view"));
    expect(screen.getByTitle("Group by category")).toBeInTheDocument();
  });

  it("shows skill count in header", async () => {
    renderPage();
    await waitForSkills();
    expect(screen.getByText(/3 skills published/)).toBeInTheDocument();
  });

  it("shows no-results message when category filter matches nothing after search", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForSkills();

    // Filter to "Backend & APIs", then search for something that doesn't match
    const select = getCategorySelect();
    await user.selectOptions(select, "Backend & APIs");

    const searchInput = screen.getByPlaceholderText("Search skills...");
    await user.type(searchInput, "nonexistent");

    expect(screen.getByText("No skills match your filters")).toBeInTheDocument();
  });
});
