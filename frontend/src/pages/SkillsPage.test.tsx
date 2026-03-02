import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import type { SkillSummary } from "../types/api";
import { makeSkill } from "../test/helpers";
import SkillsPage from "./SkillsPage";

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

const ORG_PROFILES = [{ slug: "acme", is_personal: false, avatar_url: null, description: null, blog: null }];

const STATS = {
  total_skills: 3,
  total_orgs: 1,
  total_downloads: 170,
  active_categories: ["Backend & APIs", "AI & LLM", "Frontend & UI"],
};

/** Server-side filtering mock: filters SKILLS based on query params. */
function filterSkillsHandler({ request }: { request: Request }) {
  const url = new URL(request.url);
  const search = url.searchParams.get("search")?.toLowerCase();
  const category = url.searchParams.get("category");

  let filtered = [...SKILLS];
  if (search) {
    filtered = filtered.filter(
      (s) =>
        s.skill_name.toLowerCase().includes(search) ||
        s.description.toLowerCase().includes(search) ||
        s.org_slug.toLowerCase().includes(search),
    );
  }
  if (category) {
    filtered = filtered.filter((s) => s.category === category);
  }

  return HttpResponse.json({
    items: filtered,
    total: filtered.length,
    page: 1,
    page_size: 12,
    total_pages: 1,
  });
}

const server = setupServer(
  http.get("/v1/skills", filterSkillsHandler),
  http.get("/v1/taxonomy", () => HttpResponse.json(TAXONOMY)),
  http.get("/v1/orgs/profiles", () => HttpResponse.json(ORG_PROFILES)),
  http.get("/v1/stats", () => HttpResponse.json(STATS)),
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
    const optgroups = select.querySelectorAll("optgroup");
    expect(optgroups.length).toBeGreaterThan(0);
    expect(select.value).toBe("all");
  });

  it("filters skills by category selection", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForSkills();

    const select = getCategorySelect();
    await user.selectOptions(select, "Backend & APIs");

    // Server-side filter returns only "api-gen"
    await waitFor(() => {
      expect(screen.getByText("api-gen")).toBeInTheDocument();
      expect(screen.queryByText("llm-tool")).not.toBeInTheDocument();
      expect(screen.queryByText("css-fix")).not.toBeInTheDocument();
    });
  });

  it("shows grouped view when toggle is clicked", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForSkills();

    const toggleButton = screen.getByTitle("Group by category");
    await user.click(toggleButton);

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
    expect(screen.getByText(/3 skills/)).toBeInTheDocument();
  });

  it("shows 'Removed from GitHub' badge when source_repo_removed is true", async () => {
    const removedSkill = makeSkill({
      skill_name: "removed-skill",
      description: "This skill's repo was deleted",
      source_repo_removed: true,
    });
    server.use(
      http.get("/v1/skills", () =>
        HttpResponse.json({
          items: [removedSkill],
          total: 1,
          page: 1,
          page_size: 12,
          total_pages: 1,
        }),
      ),
    );
    renderPage();
    await screen.findByText("removed-skill");
    expect(screen.getByText("Removed from GitHub")).toBeInTheDocument();
  });

  it("shows no-results message when search matches nothing", async () => {
    const user = userEvent.setup();
    renderPage();
    await waitForSkills();

    const select = getCategorySelect();
    await user.selectOptions(select, "Backend & APIs");

    // Wait for category filter to take effect
    await waitFor(() => {
      expect(screen.queryByText("llm-tool")).not.toBeInTheDocument();
    });

    const searchInput = screen.getByPlaceholderText(/Search skills/);
    await user.type(searchInput, "nonexistent");

    // Wait for debounce + server response
    await waitFor(
      () => {
        expect(screen.getByText("No skills match your filters")).toBeInTheDocument();
      },
      { timeout: 2000 },
    );
  });
});
