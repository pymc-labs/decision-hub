import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { MemoryRouter } from "react-router-dom";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { AskResponse } from "../types/api";
import AskModal from "./AskModal";

// jsdom + Node 22 localStorage can be flaky — use a Map-backed mock.
let store: Record<string, string> = {};
const storageMock: Storage = {
  get length() { return Object.keys(store).length; },
  key(i: number) { return Object.keys(store)[i] ?? null; },
  getItem(k: string) { return store[k] ?? null; },
  setItem(k: string, v: string) { store[k] = v; },
  removeItem(k: string) { delete store[k]; },
  clear() { store = {}; },
};

// --- Test data ---

const ASK_RESPONSE: AskResponse = {
  query: "analyze data",
  answer: "Here are some **great skills** for data analysis.",
  skills: [
    {
      org_slug: "acme",
      skill_name: "data-tool",
      description: "Analyzes datasets with statistics",
      safety_rating: "A",
      reason: "Best match for your data analysis needs",
      author: "alice",
      category: "Data Science",
      download_count: 500,
      latest_version: "2.1.0",
      source_repo_url: "https://github.com/acme/data-tool",
      gauntlet_summary: null,
      github_stars: 120,
      github_license: "MIT",
    },
  ],
  category: "Data Science",
};

const SECOND_RESPONSE: AskResponse = {
  query: "more details",
  answer: "Here is more information about those skills.",
  skills: [],
  category: null,
};

// --- MSW setup ---

let askCallCount = 0;

const server = setupServer(
  http.post("/v1/ask", async () => {
    askCallCount++;
    if (askCallCount === 1) {
      return HttpResponse.json(ASK_RESPONSE);
    }
    return HttpResponse.json(SECOND_RESPONSE);
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  askCallCount = 0;
});
afterAll(() => server.close());

// --- Helpers ---

function renderModal(isOpen = true) {
  const onClose = vi.fn();
  const result = render(
    <MemoryRouter>
      <AskModal isOpen={isOpen} onClose={onClose} />
    </MemoryRouter>,
  );
  return { onClose, ...result };
}

// --- Tests ---

describe("AskModal", () => {
  beforeEach(() => {
    // Reset body overflow that the component sets
    document.body.style.overflow = "";
    store = {};
    vi.stubGlobal("localStorage", storageMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("does not render when isOpen is false", () => {
    renderModal(false);
    expect(screen.queryByText("Ask Decision Hub")).not.toBeInTheDocument();
  });

  it("renders modal header when open", () => {
    renderModal();
    expect(screen.getByText("Ask Decision Hub")).toBeInTheDocument();
  });

  it("shows empty state with suggestions when no messages", () => {
    renderModal();
    expect(screen.getByText("What are you looking for?")).toBeInTheDocument();
    expect(screen.getByText("Analyze experimental results using Bayesian methods")).toBeInTheDocument();
    expect(screen.getByText("Automate code review and pull request quality checks")).toBeInTheDocument();
    expect(screen.getByText("Generate structured data from APIs and transform it")).toBeInTheDocument();
  });

  it("populates input when suggestion button is clicked", async () => {
    const user = userEvent.setup();
    renderModal();

    await user.click(screen.getByText("Analyze experimental results using Bayesian methods"));

    const input = screen.getByPlaceholderText("Ask about skills...");
    expect(input).toHaveValue("Analyze experimental results using Bayesian methods");
  });

  it("submits query and shows response with markdown", async () => {
    const user = userEvent.setup();
    renderModal();

    const input = screen.getByPlaceholderText("Ask about skills...");
    await user.type(input, "analyze data");
    await user.click(screen.getByRole("button", { name: "Send" }));

    // User message should appear immediately
    expect(screen.getByText("analyze data")).toBeInTheDocument();

    // Wait for response (loading state may be too transient to catch reliably)
    await waitFor(() => {
      expect(
        screen.getByText(/great skills/),
      ).toBeInTheDocument();
    });

    // Loading should be gone after response
    expect(screen.queryByText("Searching skills...")).not.toBeInTheDocument();
  });

  it("renders skill cards with metadata and links", async () => {
    const user = userEvent.setup();
    renderModal();

    const input = screen.getByPlaceholderText("Ask about skills...");
    await user.type(input, "analyze data");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByText("acme/data-tool")).toBeInTheDocument();
    });

    // Check skill card metadata
    expect(screen.getByText("Analyzes datasets with statistics")).toBeInTheDocument();
    expect(screen.getByText("Best match for your data analysis needs")).toBeInTheDocument();
    expect(screen.getByText("Data Science")).toBeInTheDocument();
    expect(screen.getByText("by alice")).toBeInTheDocument();

    // Verify skill card links to detail page
    const skillLink = screen.getByText("acme/data-tool").closest("a");
    expect(skillLink).toHaveAttribute("href", "/skills/acme/data-tool");
  });

  it("supports multi-turn conversation", async () => {
    const user = userEvent.setup();
    renderModal();

    // First message
    const input = screen.getByPlaceholderText("Ask about skills...");
    await user.type(input, "analyze data");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByText(/great skills/)).toBeInTheDocument();
    });

    // Second message
    await user.type(screen.getByPlaceholderText("Ask about skills..."), "more details");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(
        screen.getByText("Here is more information about those skills."),
      ).toBeInTheDocument();
    });

    // Both user messages should be visible
    expect(screen.getByText("analyze data")).toBeInTheDocument();
    expect(screen.getByText("more details")).toBeInTheDocument();
  });

  it("closes modal on Escape key", async () => {
    const user = userEvent.setup();
    const { onClose } = renderModal();

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes modal on overlay click", async () => {
    const user = userEvent.setup();
    const { onClose, container } = renderModal();

    // The overlay is the outermost div rendered by the component.
    // It has the onClick={onClose} handler. We find it as the first
    // child of the render container.
    const overlay = container.firstElementChild!;
    await user.click(overlay);

    expect(onClose).toHaveBeenCalled();
  });

  it("closes modal via close button", async () => {
    const user = userEvent.setup();
    const { onClose } = renderModal();

    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("disables input during loading", async () => {
    const user = userEvent.setup();
    // Use a delayed response to catch the loading state
    server.use(
      http.post("/v1/ask", async () => {
        await new Promise((resolve) => setTimeout(resolve, 100));
        return HttpResponse.json(ASK_RESPONSE);
      }),
    );

    renderModal();

    const input = screen.getByPlaceholderText("Ask about skills...");
    await user.type(input, "test query");
    await user.click(screen.getByRole("button", { name: "Send" }));

    // Input should be disabled while loading
    await waitFor(() => {
      expect(screen.getByPlaceholderText("Ask about skills...")).toBeDisabled();
    });

    // Wait for response to complete
    await waitFor(() => {
      expect(screen.getByPlaceholderText("Ask about skills...")).not.toBeDisabled();
    });
  });

  it("shows error state on API failure", async () => {
    server.use(
      http.post("/v1/ask", () =>
        new HttpResponse("Internal Server Error", { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderModal();

    const input = screen.getByPlaceholderText("Ask about skills...");
    await user.type(input, "broken query");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByText(/API 500/)).toBeInTheDocument();
    });
  });

  it("send button is disabled when input is empty", () => {
    renderModal();
    const sendBtn = screen.getByRole("button", { name: "Send" });
    expect(sendBtn).toBeDisabled();
  });

  describe("recently viewed strip", () => {
    const STORAGE_KEY = "dhub:recently-viewed";

    it("does not show recently viewed section when localStorage is empty", () => {
      renderModal();
      expect(screen.queryByText("Recently Viewed")).not.toBeInTheDocument();
    });

    it("renders recently viewed skills from localStorage", () => {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify([
          {
            org_slug: "acme",
            skill_name: "cool-skill",
            description: "A cool skill",
            safety_rating: "A",
          },
        ]),
      );

      renderModal();

      expect(screen.getByText("Recently Viewed")).toBeInTheDocument();
      expect(screen.getByText("acme/cool-skill")).toBeInTheDocument();
      expect(screen.getByText("A cool skill")).toBeInTheDocument();
    });

    it("links recently viewed items to skill detail page", () => {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify([
          {
            org_slug: "acme",
            skill_name: "cool-skill",
            description: "A cool skill",
            safety_rating: "B",
          },
        ]),
      );

      renderModal();

      const link = screen.getByText("acme/cool-skill").closest("a");
      expect(link).toHaveAttribute("href", "/skills/acme/cool-skill");
    });

    it("calls onClose when a recently viewed item is clicked", async () => {
      const user = userEvent.setup();
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify([
          {
            org_slug: "acme",
            skill_name: "cool-skill",
            description: "desc",
            safety_rating: "A",
          },
        ]),
      );

      const { onClose } = renderModal();

      await user.click(screen.getByText("acme/cool-skill"));
      expect(onClose).toHaveBeenCalled();
    });
  });
});
