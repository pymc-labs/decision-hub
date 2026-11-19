import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
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
  const org = url.searchParams.get("org");
  const grade = url.searchParams.get("grade");

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
  if (org) filtered = filtered.filter((s) => s.org_slug === org);
  if (grade) filtered = filtered.filter((s) => s.safety_rating === grade);

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
afterEach(() => {
  server.resetHandlers();
  vi.useRealTimers();
});
afterAll(() => server.close());

function renderPage(url = "/skills") {
  window.history.replaceState(null, "", url);
  return render(
    <BrowserRouter>
      <Routes><Route path="/skills" element={<SkillsPage />} /></Routes>
    </BrowserRouter>,
  );
}

/** Wait for the skill grid to load (first skill name visible). */
async function waitForSkills() {
  await screen.findByText("api-gen");
}

function getCategorySelect(): HTMLSelectElement {
  return screen.getByRole("combobox", { name: "Filter by category" });
}

function recordSkillRequests() {
  const requests: URLSearchParams[] = [];
  server.use(http.get("/v1/skills", (info) => {
    requests.push(new URL(info.request.url).searchParams);
    return filterSkillsHandler(info);
  }));
  return requests;
}

describe("SkillsPage", () => {
  it("opens a shared URL with every control and the first results request in sync", async () => {
    const requests = recordSkillRequests();
    renderPage("/skills?search=api&org=acme&category=Backend+%26+APIs&grade=A&sort=downloads&sort_dir=asc");
    await waitForSkills();
    expect(screen.getByRole("textbox")).toHaveValue("api");
    expect(screen.getByLabelText("Filter by organization")).toHaveValue("acme");
    expect(getCategorySelect()).toHaveValue("Backend & APIs");
    expect(screen.getByLabelText("Filter by safety grade")).toHaveValue("A");
    expect(screen.getByLabelText("Sort skills by")).toHaveValue("downloads");
    expect(screen.getByLabelText("Toggle sort direction")).toHaveAttribute("title", expect.stringMatching(/^Ascending/));
    expect(screen.queryByText("llm-tool")).not.toBeInTheDocument();
    expect(requests.map((params) => Object.fromEntries(params))).toEqual([{
      page: "1", page_size: "12", search: "api", org: "acme", category: "Backend & APIs",
      grade: "A", sort: "downloads", sort_dir: "asc",
    }]);
  });

  it("shares edits, reopens the same empty search, and resets only registry parameters", async () => {
    const user = userEvent.setup();
    const { unmount } = renderPage("/skills?ref=one&ref=two#results");
    await waitForSkills();
    await user.selectOptions(screen.getByLabelText("Filter by organization"), "acme");
    await user.selectOptions(getCategorySelect(), "AI & LLM");
    await user.selectOptions(screen.getByLabelText("Filter by safety grade"), "A");
    await user.selectOptions(screen.getByLabelText("Sort skills by"), "name");
    expect(screen.getByLabelText("Toggle sort direction")).toHaveAttribute("title", expect.stringMatching(/^Ascending/));
    await user.click(screen.getByLabelText("Toggle sort direction"));
    await user.type(screen.getByRole("textbox"), "C++ & ML");
    await screen.findByText("No skills match your filters");
    const { pathname, search, hash } = window.location;
    const params = new URLSearchParams(search);
    expect(Object.fromEntries(params)).toEqual({
      ref: "two", org: "acme", category: "AI & LLM", grade: "A", sort: "name", sort_dir: "desc", search: "C++ & ML",
    });
    expect(params.getAll("ref")).toEqual(["one", "two"]);
    expect(hash).toBe("#results");

    unmount();
    renderPage(pathname + search + hash);
    await screen.findByText("No skills match your filters");
    expect(screen.getByRole("textbox")).toHaveValue("C++ & ML");
    await user.click(screen.getByRole("button", { name: "Reset filters" }));
    await waitForSkills();
    expect(window.location).toMatchObject({ search: "?ref=one&ref=two", hash });
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.getByLabelText("Sort skills by")).toHaveValue("updated");
  });

  it("debounces typing into one history entry and cancels an unfinished edit on Back", async () => {
    const requests = recordSkillRequests();
    renderPage();
    await waitForSkills();
    const input = screen.getByRole("textbox");
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    fireEvent.change(input, { target: { value: "a" } });
    act(() => vi.advanceTimersByTime(200));
    fireEvent.change(input, { target: { value: "api" } });
    act(() => vi.advanceTimersByTime(299));
    expect(window.location.search).toBe("");
    expect(requests).toHaveLength(1);
    await act(async () => { vi.advanceTimersByTime(1); });
    expect(window.location.search).toBe("?search=api");
    fireEvent.change(input, { target: { value: "discard me" } });
    await act(async () => {
      window.history.back();
      await vi.advanceTimersByTimeAsync(10);
    });
    act(() => vi.advanceTimersByTime(300));
    expect(window.location.search).toBe("");
    expect(input).toHaveValue("");
    await act(async () => {
      window.history.forward();
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(input).toHaveValue("api");
    vi.useRealTimers();
    await waitFor(() => expect(requests.map((params) => params.get("search"))).toEqual([null, "api", null, "api"]));
  });

  it("applies a pending query with a filter change, and removes a blank query on its own", async () => {
    const user = userEvent.setup();
    renderPage("/skills?ref=catalog");
    await waitForSkills();
    const input = screen.getByRole("textbox");
    await user.type(input, "api");
    await user.selectOptions(getCategorySelect(), "Backend & APIs");
    const combined = new URLSearchParams(window.location.search);
    expect(combined.get("search")).toBe("api");
    expect(combined.get("category")).toBe("Backend & APIs");
    await user.clear(input);
    await user.type(input, "   ");
    await waitFor(() => expect(new URLSearchParams(window.location.search).has("search")).toBe(false));
    expect(new URLSearchParams(window.location.search).get("category")).toBe("Backend & APIs");
  });

  it("keeps malformed and oversized filter values out of requests", async () => {
    const requests = recordSkillRequests();
    const longValue = "x".repeat(201);
    renderPage(`/skills?search=++&grade=F&sort=typo&sort_dir=sideways&org=${longValue}&category=${longValue}`);
    await waitForSkills();
    expect(requests.map((params) => Object.fromEntries(params))).toEqual([{
      page: "1", page_size: "12", sort: "updated", sort_dir: "desc",
    }]);
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.getByLabelText("Filter by safety grade")).toHaveDisplayValue("All Grades");
    expect(window.location.search).toBe("");
  });

  it("cleans a copied query once, retaining Unicode and repeated unrelated parameters", async () => {
    const requests = recordSkillRequests();
    const search = "🚀".repeat(200);
    const params = new URLSearchParams([
      ["search", "\u0000" + search + "extra"], ["search", "duplicate"],
      ["grade", "B"], ["grade", "C"], ["ref", "one"], ["ref", "two"],
    ]);
    const historyLength = window.history.length;
    renderPage("/skills?" + params);
    await screen.findByText("No skills match your filters");
    expect(screen.getByRole("textbox")).toHaveValue(search);
    const cleaned = new URLSearchParams(window.location.search);
    expect(cleaned.getAll("search")).toEqual([search]);
    expect(cleaned.getAll("grade")).toEqual(["B"]);
    expect(cleaned.getAll("ref")).toEqual(["one", "two"]);
    expect(window.history.length).toBe(historyLength);
    expect(requests.map((request) => request.get("search"))).toEqual([search]);
  });

  it("discards pending text on reset even when the URL is already clear", async () => {
    const requests = recordSkillRequests();
    renderPage("/skills?ref=one");
    await waitForSkills();
    const input = screen.getByRole("textbox");
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    fireEvent.change(input, { target: { value: "draft" } });
    fireEvent.click(screen.getByRole("button", { name: "Reset filters" }));
    await act(async () => { vi.advanceTimersByTime(300); });
    expect(input).toHaveValue("");
    expect(window.location.search).toBe("?ref=one");
    expect(requests).toHaveLength(1);
  });

  it("keeps unavailable facets visible and lets the reader recover from an empty link", async () => {
    const user = userEvent.setup();
    renderPage("/skills?org=retired&category=Old+category&sort=name&sort_dir=bad");
    await screen.findByText("No skills match your filters");
    expect(screen.getByLabelText("Filter by organization")).toHaveDisplayValue("retired");
    expect(getCategorySelect()).toHaveDisplayValue("Old category");
    expect(screen.getByLabelText("Toggle sort direction")).toHaveAttribute("title", expect.stringMatching(/^Ascending/));
    await user.click(screen.getByRole("button", { name: "Reset filters" }));
    await waitForSkills();
    expect(window.location.search).toBe("");
  });

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
    expect(select).toHaveDisplayValue("All Categories");
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
