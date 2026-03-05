import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import OrgsPage from "./OrgsPage";

beforeAll(() => {
  // jsdom does not implement IntersectionObserver
  global.IntersectionObserver = vi.fn().mockImplementation(() => ({
    observe: vi.fn(),
    unobserve: vi.fn(),
    disconnect: vi.fn(),
  }));
});

const server = setupServer(
  http.get("/v1/orgs/stats", () =>
    HttpResponse.json({ items: [{ slug: "acme", skill_count: 5, total_downloads: 100, is_personal: false, avatar_url: null }], total: 1 })),
  http.get("/v1/stats", () =>
    HttpResponse.json({ total_skills: 5, total_orgs: 1, total_downloads: 100, active_categories: [] })),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("OrgsPage", () => {
  it("renders page title", () => {
    render(<MemoryRouter><OrgsPage /></MemoryRouter>);
    expect(screen.getByText(/Organizations/i)).toBeInTheDocument();
  });

  it("renders org cards after loading", async () => {
    render(<MemoryRouter><OrgsPage /></MemoryRouter>);
    expect(await screen.findByText("acme")).toBeInTheDocument();
  });
});
