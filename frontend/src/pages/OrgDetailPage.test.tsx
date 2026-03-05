import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import OrgDetailPage from "./OrgDetailPage";

const server = setupServer(
  http.get("/v1/orgs/acme/profile", () =>
    HttpResponse.json({ slug: "acme", is_personal: false, avatar_url: null, description: "An org", blog: null })),
  http.get("/v1/skills", () =>
    HttpResponse.json({ items: [], total: 0, page: 1, page_size: 12, total_pages: 0 })),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("OrgDetailPage", () => {
  it("renders org name", async () => {
    render(
      <MemoryRouter initialEntries={["/orgs/acme"]}>
        <Routes><Route path="/orgs/:orgSlug" element={<OrgDetailPage />} /></Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("acme")).toBeInTheDocument();
  });
});
