import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import HomePage from "./HomePage";

beforeAll(() => {
  // jsdom does not implement IntersectionObserver
  global.IntersectionObserver = vi.fn().mockImplementation(() => ({
    observe: vi.fn(),
    unobserve: vi.fn(),
    disconnect: vi.fn(),
  }));
});

const STATS = { total_skills: 42, total_orgs: 5, total_downloads: 1000, active_categories: [] };
const SKILLS = { items: [], total: 0, page: 1, page_size: 6, total_pages: 0 };

const server = setupServer(
  http.get("/v1/stats", () => HttpResponse.json(STATS)),
  http.get("/v1/skills", () => HttpResponse.json(SKILLS)),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("HomePage", () => {
  it("renders hero headline", () => {
    render(<MemoryRouter><HomePage /></MemoryRouter>);
    expect(screen.getByText("DECISION")).toBeInTheDocument();
  });

  it("renders install section", () => {
    render(<MemoryRouter><HomePage /></MemoryRouter>);
    expect(screen.getByText(/Install the CLI/i)).toBeInTheDocument();
  });

  it("renders value proposition cards", () => {
    render(<MemoryRouter><HomePage /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: /Automated Evals/i })).toBeInTheDocument();
  });
});
