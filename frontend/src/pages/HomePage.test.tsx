import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import {
  makeSkill,
  makeRegistryStats,
  makePaginatedResponse,
} from "../test/helpers";
import HomePage from "./HomePage";

// --- Test data ---

const STATS = makeRegistryStats({
  total_skills: 42,
  total_orgs: 5,
  total_publishers: 10,
  total_downloads: 1000,
});

const FEATURED_SKILLS = [
  makeSkill({
    org_slug: "acme",
    skill_name: "data-tool",
    description: "Analyzes datasets",
    latest_version: "2.1.0",
    safety_rating: "A",
    category: "Data Science & Statistics",
    download_count: 500,
    github_stars: 120,
  }),
  makeSkill({
    org_slug: "pymc-labs",
    skill_name: "pymc-modeling",
    description: "Bayesian modeling with PyMC",
    latest_version: "1.2.0",
    safety_rating: "A",
    category: "Data Science & Statistics",
    download_count: 300,
  }),
];

// --- MSW setup ---

const server = setupServer(
  http.get("/v1/stats", () => HttpResponse.json(STATS)),
  http.get("/v1/skills", () =>
    HttpResponse.json(makePaginatedResponse(FEATURED_SKILLS)),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// --- IntersectionObserver mock for useCountUp ---

// The global setup.ts provides a no-op IntersectionObserver stub so that
// components never crash during render or cleanup. Here we override it
// per-test to actually trigger the animation for useCountUp, but we
// restore it afterward rather than calling vi.unstubAllGlobals() (which
// would remove the stub *before* React cleanup runs and cause errors).

const savedIO = globalThis.IntersectionObserver;

beforeEach(() => {
  // Override IntersectionObserver: when observe() is called, immediately fire
  // the callback with isIntersecting=true so useCountUp animation starts.
  globalThis.IntersectionObserver = class {
    private cb: IntersectionObserverCallback;
    constructor(cb: IntersectionObserverCallback) {
      this.cb = cb;
    }
    observe() {
      // Defer so the constructor has fully returned before the callback
      // tries to call disconnect() on the returned observer instance.
      queueMicrotask(() => {
        this.cb(
          [{ isIntersecting: true } as IntersectionObserverEntry],
          this as unknown as IntersectionObserver,
        );
      });
    }
    unobserve() {}
    disconnect() {}
  } as unknown as typeof IntersectionObserver;
});

afterEach(() => {
  // Restore the no-op stub from setup.ts so React cleanup doesn't crash.
  globalThis.IntersectionObserver = savedIO;
});

// Clipboard spy is set up per-test after userEvent.setup() since
// userEvent replaces navigator.clipboard with its own implementation.

// --- Helpers ---

function renderPage() {
  return render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  );
}

// --- Tests ---

describe("HomePage", () => {
  it("renders hero section with title", async () => {
    renderPage();
    expect(screen.getByText("DECISION")).toBeInTheDocument();
    expect(screen.getByText("HUB")).toBeInTheDocument();
    expect(
      screen.getByText("Trusted Skills for AI Agents in Data Science and Beyond"),
    ).toBeInTheDocument();
  });

  it("renders stats section labels", async () => {
    renderPage();

    // Wait for data to load. The stat labels are always present once rendered.
    await waitFor(() => {
      expect(screen.getByText("Skills Published")).toBeInTheDocument();
      expect(screen.getByText("Organizations")).toBeInTheDocument();
      expect(screen.getByText("Downloads")).toBeInTheDocument();
      expect(screen.getByText("Publishers")).toBeInTheDocument();
    });
  });

  it("renders featured skills grid with skill cards", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("data-tool")).toBeInTheDocument();
    });
    expect(screen.getByText("pymc-modeling")).toBeInTheDocument();
    expect(screen.getByText("Analyzes datasets")).toBeInTheDocument();
    expect(screen.getByText("Bayesian modeling with PyMC")).toBeInTheDocument();
  });

  it("skill cards link to detail pages", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("data-tool")).toBeInTheDocument();
    });

    const skillLink = screen.getByText("data-tool").closest("a");
    expect(skillLink).toHaveAttribute("href", "/skills/acme/data-tool");
  });

  it("skill cards show category badges", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("data-tool")).toBeInTheDocument();
    });

    // Both skills have Data Science & Statistics category
    const categoryBadges = screen.getAllByText("Data Science & Statistics");
    expect(categoryBadges.length).toBeGreaterThanOrEqual(1);
  });

  it("toggles OS tab and changes install command", async () => {
    const user = userEvent.setup();
    renderPage();

    // Default is macOS / Linux
    const unixTab = screen.getByText("macOS / Linux");
    const windowsTab = screen.getByText("Windows");

    expect(unixTab).toBeInTheDocument();
    expect(windowsTab).toBeInTheDocument();

    // Check the unix install command is shown in the terminal block
    // (use getAllByText since there are multiple elements with "uv tool install")
    const unixElements = screen.getAllByText(/uv tool install dhub-cli/);
    expect(unixElements.length).toBeGreaterThanOrEqual(1);

    // Switch to Windows
    await user.click(windowsTab);

    // Windows command should now be shown
    expect(screen.getByText(/irm https:\/\/astral\.sh\/uv\/install\.ps1/)).toBeInTheDocument();
  });

  it("copies install command to clipboard on copy button click", async () => {
    // userEvent.setup() replaces navigator.clipboard, so we must spy
    // after calling setup() to intercept the correct object.
    const user = userEvent.setup();
    renderPage();

    const clipboardSpy = vi.spyOn(navigator.clipboard, "writeText");

    const copyBtn = screen.getByRole("button", { name: "Copy to clipboard" });
    await user.click(copyBtn);

    expect(clipboardSpy).toHaveBeenCalledWith(
      expect.stringContaining("uv tool install dhub-cli"),
    );

    clipboardSpy.mockRestore();
  });

  it("'Ask the Registry' button dispatches open-ask-modal custom event", async () => {
    const user = userEvent.setup();
    const eventHandler = vi.fn();
    window.addEventListener("open-ask-modal", eventHandler);

    renderPage();

    const askBtn = screen.getByText("Ask the Registry");
    await user.click(askBtn);

    expect(eventHandler).toHaveBeenCalledTimes(1);

    window.removeEventListener("open-ask-modal", eventHandler);
  });

  it("renders value proposition cards", async () => {
    renderPage();

    expect(screen.getByText("Automated Evals")).toBeInTheDocument();
    expect(screen.getByText("Security Grading")).toBeInTheDocument();
    expect(screen.getByText("Conversational Search")).toBeInTheDocument();
  });

  it("renders quick start examples section", async () => {
    renderPage();

    expect(screen.getByText("Quick Start")).toBeInTheDocument();
    expect(screen.getByText("Search with natural language")).toBeInTheDocument();
    expect(screen.getByText("Install in one command")).toBeInTheDocument();
  });
});
