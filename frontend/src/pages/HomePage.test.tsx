import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import {
  renderWithRouter,
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
  return renderWithRouter(<HomePage />);
}

// --- Tests ---

describe("HomePage", () => {
  it("renders hero section with narrative headline", async () => {
    renderPage();
    expect(
      screen.getByText("Your AI agent doesn't know data science."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Give it a skill that does."),
    ).toBeInTheDocument();
  });

  it("renders inline stats bar in hero", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Skills")).toBeInTheDocument();
      expect(screen.getByText("Organizations")).toBeInTheDocument();
      expect(screen.getByText("Downloads")).toBeInTheDocument();
    });

    // Publishers stat is intentionally dropped
    expect(screen.queryByText("Publishers")).not.toBeInTheDocument();
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

  it("toggles install tabs between pip, uv, and fresh install", async () => {
    const user = userEvent.setup();
    renderPage();

    // Default tab is pip (also appears in the agent steps section)
    const pipTexts = screen.getAllByText("pip install dhub-cli");
    expect(pipTexts.length).toBeGreaterThanOrEqual(1);

    // Verify ARIA tab attributes
    const pipTab = screen.getByRole("tab", { name: "pip" });
    expect(pipTab).toHaveAttribute("aria-selected", "true");

    // Switch to uv
    const uvTab = screen.getByRole("tab", { name: "uv" });
    await user.click(uvTab);
    expect(screen.getByText("uv tool install dhub-cli")).toBeInTheDocument();
    expect(uvTab).toHaveAttribute("aria-selected", "true");
    expect(pipTab).toHaveAttribute("aria-selected", "false");

    // Switch to fresh install
    const freshTab = screen.getByRole("tab", { name: "fresh install" });
    await user.click(freshTab);
    expect(screen.getByText(/curl -LsSf/)).toBeInTheDocument();
  });

  it("copies install command to clipboard on copy button click", async () => {
    const user = userEvent.setup();
    renderPage();

    const clipboardSpy = vi.spyOn(navigator.clipboard, "writeText")
      .mockResolvedValue(undefined);

    const copyBtn = screen.getByRole("button", { name: "Copy to clipboard" });
    await user.click(copyBtn);

    expect(clipboardSpy).toHaveBeenCalledWith("pip install dhub-cli");

    clipboardSpy.mockRestore();
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

  it("renders Supercharge Your Agent section with steps", async () => {
    renderPage();

    expect(screen.getByText("Supercharge Your Agent")).toBeInTheDocument();
    expect(screen.getByText("Install the CLI")).toBeInTheDocument();
    expect(screen.getByText("Add the dhub skill")).toBeInTheDocument();
    expect(screen.getByText("Just ask")).toBeInTheDocument();
  });

  it("renders Search Skills and How It Works CTAs", async () => {
    const user = userEvent.setup();
    const eventHandler = vi.fn();
    window.addEventListener("open-ask-modal", eventHandler);

    renderPage();

    const searchBtn = screen.getByText("Search Skills");
    expect(searchBtn).toBeInTheDocument();
    await user.click(searchBtn);
    expect(eventHandler).toHaveBeenCalledTimes(1);

    const howItWorksLink = screen.getByText("How It Works").closest("a");
    expect(howItWorksLink).toHaveAttribute("href", "/how-it-works");

    window.removeEventListener("open-ask-modal", eventHandler);
  });
});
