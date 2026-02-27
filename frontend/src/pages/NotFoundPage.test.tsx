import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import NotFoundPage from "./NotFoundPage";

// Mock useSEO to avoid side effects
vi.mock("../hooks/useSEO", () => ({
  useSEO: vi.fn(),
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <NotFoundPage />
    </MemoryRouter>,
  );
}

describe("NotFoundPage", () => {
  it("renders 404 heading", () => {
    renderPage();
    expect(screen.getByText("404")).toBeInTheDocument();
  });

  it("renders page not found message", () => {
    renderPage();
    expect(screen.getByText("Page not found")).toBeInTheDocument();
  });

  it("renders description text", () => {
    renderPage();
    expect(
      screen.getByText(/The page you're looking for doesn't exist/),
    ).toBeInTheDocument();
  });

  it("renders a link back to home", () => {
    renderPage();
    const link = screen.getByText(/Back to home/);
    expect(link).toBeInTheDocument();
    expect(link.closest("a")).toHaveAttribute("href", "/");
  });
});
