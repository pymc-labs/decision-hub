import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import SkillDetailPage from "./SkillDetailPage";

const mockSkill = {
  org_slug: "acme", skill_name: "test-skill", description: "A great skill",
  latest_version: "1.0.0", safety_rating: "A", updated_at: "2025-01-01T00:00:00Z",
  author: "dev", download_count: 42, is_personal_org: false, category: "Backend & APIs",
  source_repo_url: "https://github.com/acme/test", manifest_path: null,
  source_repo_removed: false, github_stars: 10, github_forks: 2, github_watchers: 5,
  github_license: "MIT", github_is_archived: false, is_auto_synced: false,
};

const server = setupServer(
  http.get("/v1/skills/acme/test-skill/summary", () => HttpResponse.json(mockSkill)),
  http.get("/v1/skills/acme/test-skill/eval-report", () =>
    HttpResponse.json({ eval_id: null, status: null, results: null })),
  http.get("/v1/skills/acme/test-skill/audit-log", () =>
    HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20, total_pages: 0 })),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/skills/acme/test-skill"]}>
      <Routes><Route path="/skills/:orgSlug/:skillName" element={<SkillDetailPage />} /></Routes>
    </MemoryRouter>,
  );
}

describe("SkillDetailPage", () => {
  it("renders skill name", async () => {
    renderPage();
    expect(await screen.findByText("test-skill")).toBeInTheDocument();
  });

  it("renders grade badge", async () => {
    renderPage();
    expect(await screen.findByText("A")).toBeInTheDocument();
  });

  it("renders tabs", async () => {
    renderPage();
    await screen.findByText("test-skill");
    expect(screen.getByText("Overview")).toBeInTheDocument();
  });
});
