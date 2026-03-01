import { render, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import HomePage from "./HomePage";

// Mock IntersectionObserver for jsdom (used by AnimatedTerminal and useCountUp)
beforeEach(() => {
  const mockObserver = vi.fn(() => ({
    observe: vi.fn(),
    unobserve: vi.fn(),
    disconnect: vi.fn(),
  }));
  vi.stubGlobal("IntersectionObserver", mockObserver);
});

const STATS = {
  total_skills: 42,
  total_orgs: 5,
  total_publishers: 8,
  total_downloads: 1234,
  active_categories: ["Data Science & Statistics"],
};

const SKILLS = [
  {
    org_slug: "acme",
    skill_name: "data-tool",
    description: "Analyzes data",
    latest_version: "1.0.0",
    updated_at: "2025-01-01T00:00:00Z",
    safety_rating: "A",
    author: "dev",
    download_count: 100,
    is_personal_org: false,
    category: "Data Science & Statistics",
    source_repo_url: null,
    source_repo_removed: false,
    github_stars: null,
    github_forks: null,
    github_watchers: null,
    github_is_archived: null,
    github_license: null,
    is_auto_synced: false,
  },
];

const server = setupServer(
  http.get("/v1/stats", () => HttpResponse.json(STATS)),
  http.get("/v1/skills", () =>
    HttpResponse.json({
      items: SKILLS,
      total: 1,
      page: 1,
      page_size: 6,
      total_pages: 1,
    }),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPage() {
  return render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  );
}

describe("HomePage", () => {
  it("renders hero section with title and tagline", () => {
    renderPage();
    expect(screen.getByText("Decision Hub")).toBeInTheDocument();
    expect(
      screen.getByText("Trusted Skills for AI Agents in Data Science and Beyond"),
    ).toBeInTheDocument();
  });

  it("renders CTA buttons", () => {
    renderPage();
    expect(screen.getByText("Ask the Registry")).toBeInTheDocument();
    expect(screen.getByText("How It Works")).toBeInTheDocument();
  });

  it("renders stat labels", () => {
    renderPage();
    expect(screen.getByText("Skills")).toBeInTheDocument();
    expect(screen.getByText("Organizations")).toBeInTheDocument();
    expect(screen.getByText("Downloads")).toBeInTheDocument();
    expect(screen.getByText("Publishers")).toBeInTheDocument();
  });

  it("renders value proposition cards", () => {
    renderPage();
    expect(screen.getByText("Automated Evals")).toBeInTheDocument();
    expect(screen.getByText("Security Grading")).toBeInTheDocument();
    expect(screen.getByText("Conversational Search")).toBeInTheDocument();
  });

  it("renders Built for Agents section", () => {
    renderPage();
    expect(screen.getByText("Built for Agents")).toBeInTheDocument();
  });

  it("renders Install the CLI section with OS toggle", () => {
    renderPage();
    expect(screen.getByText("Install the CLI")).toBeInTheDocument();
    expect(screen.getByText("macOS / Linux")).toBeInTheDocument();
    expect(screen.getByText("Windows")).toBeInTheDocument();
  });

  it("renders Quick Start section", () => {
    renderPage();
    expect(screen.getByText("Quick Start")).toBeInTheDocument();
    expect(screen.getByText("Search with natural language")).toBeInTheDocument();
    expect(screen.getByText("Install in one command")).toBeInTheDocument();
  });

  it("renders bottom CTA section", () => {
    renderPage();
    expect(screen.getByText("Publish Your Skills")).toBeInTheDocument();
  });

  it("renders featured skills after data loads", async () => {
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("data-tool")).toBeInTheDocument();
    });
    expect(screen.getByText("Latest Skills")).toBeInTheDocument();
    expect(screen.getByText("acme")).toBeInTheDocument();
  });

  it("renders stat elements with initial values", () => {
    renderPage();
    // Stats start at 0 before IntersectionObserver triggers the count-up animation.
    // We verify the structure renders — the actual animated values require real IntersectionObserver.
    const statNumbers = document.querySelectorAll("[class*='statNumber']");
    expect(statNumbers.length).toBe(4);
  });
});
