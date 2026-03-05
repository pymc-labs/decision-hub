import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import {
  renderWithRouter,
  makeSkill,
  makeEvalReport,
  makeAuditLogEntry,
} from "../test/helpers";
import SkillDetailPage from "./SkillDetailPage";

// --- Test data ---

const SKILL = makeSkill({
  org_slug: "acme",
  skill_name: "data-tool",
  description: "Analyzes datasets",
  latest_version: "2.1.0",
  safety_rating: "A",
  author: "alice",
  download_count: 500,
  category: "Data Science & Statistics",
  github_stars: 120,
  github_forks: 15,
  github_license: "MIT",
  source_repo_url: "https://github.com/acme/data-tool",
});

const EVAL_REPORT = makeEvalReport({
  agent: "claude",
  judge_model: "claude-3-opus",
  passed: 2,
  total: 3,
  case_results: [
    {
      name: "basic-case",
      description: "Tests basic functionality",
      verdict: "pass",
      reasoning: "Correct output",
      agent_output: "result",
      agent_stderr: "",
      exit_code: 0,
      duration_ms: 1200,
      stage: "eval",
    },
    {
      name: "edge-case",
      description: "Tests edge case",
      verdict: "pass",
      reasoning: "Handled correctly",
      agent_output: "edge result",
      agent_stderr: "",
      exit_code: 0,
      duration_ms: 800,
      stage: "eval",
    },
    {
      name: "fail-case",
      description: "Tests failure scenario",
      verdict: "fail",
      reasoning: "Wrong output",
      agent_output: "bad result",
      agent_stderr: "error occurred",
      exit_code: 1,
      duration_ms: 500,
      stage: "eval",
    },
  ],
});

const AUDIT_LOG = [
  makeAuditLogEntry({
    id: "a1",
    semver: "2.1.0",
    grade: "A",
    publisher: "alice@example.com",
    check_results: [
      { severity: "pass", check_name: "no_shell_commands", message: "No shell commands found" },
      { severity: "pass", check_name: "no_data_exfil", message: "No data exfiltration" },
    ],
  }),
  makeAuditLogEntry({
    id: "a2",
    semver: "2.0.0",
    grade: "B",
    publisher: "bob@example.com",
    check_results: [
      { severity: "warning", check_name: "prompt_injection", message: "Potential injection" },
    ],
  }),
];

// Minimal valid zip (empty zip archive — 22 bytes)
const EMPTY_ZIP = new Uint8Array([
  0x50, 0x4b, 0x05, 0x06, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
  0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
]).buffer;

// --- MSW setup ---

const server = setupServer(
  http.get("/v1/skills/acme/data-tool/summary", () =>
    HttpResponse.json(SKILL),
  ),
  http.get("/v1/skills/acme/data-tool/eval-report", () =>
    HttpResponse.json(EVAL_REPORT),
  ),
  http.get("/v1/skills/acme/data-tool/audit-log", () =>
    HttpResponse.json({ items: AUDIT_LOG, total: 2, page: 1, page_size: 20, total_pages: 1 }),
  ),
  http.get("/v1/skills/acme/data-tool/similar", () =>
    HttpResponse.json([]),
  ),
  http.get("/v1/skills/acme/data-tool/download", () =>
    new HttpResponse(EMPTY_ZIP, {
      headers: { "Content-Type": "application/zip" },
    }),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// --- Helpers ---

function renderPage() {
  return renderWithRouter(<SkillDetailPage />, {
    initialEntries: ["/skills/acme/data-tool"],
    path: "/skills/:orgSlug/:skillName",
  });
}

// --- Tests ---

describe("SkillDetailPage", () => {
  it("shows loading spinner initially", () => {
    renderPage();
    expect(screen.getByText(/Loading acme\/data-tool/)).toBeInTheDocument();
  });

  it("renders skill name and description after loading", async () => {
    renderPage();
    await screen.findByText("data-tool");
    expect(screen.getByText("Analyzes datasets")).toBeInTheDocument();
  });

  it("renders org link in header", async () => {
    renderPage();
    await screen.findByText("data-tool");
    const orgLink = screen.getByText("acme");
    expect(orgLink.closest("a")).toHaveAttribute("href", "/orgs/acme");
  });

  it("renders sidebar metadata (version, downloads, stars, forks, license, author, category)", async () => {
    renderPage();
    await screen.findByText("data-tool");

    expect(screen.getByText("v2.1.0")).toBeInTheDocument();
    expect(screen.getByText("500")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText("15")).toBeInTheDocument();
    expect(screen.getByText("MIT")).toBeInTheDocument();
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.getByText("Data Science & Statistics")).toBeInTheDocument();
  });

  it("renders GitHub source link when source_repo_url is present", async () => {
    renderPage();
    await screen.findByText("data-tool");

    const githubLink = screen.getByText("GitHub ↗");
    expect(githubLink).toHaveAttribute(
      "href",
      "https://github.com/acme/data-tool",
    );
  });

  it("shows install button and copies to clipboard on click", async () => {
    // userEvent.setup() replaces navigator.clipboard, so we must set up
    // the spy *after* calling setup() to intercept the correct object.
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("data-tool");

    const clipboardSpy = vi.spyOn(navigator.clipboard, "writeText");

    const installBtn = screen.getByText("dhub install");
    await user.click(installBtn);

    expect(clipboardSpy).toHaveBeenCalledWith(
      "dhub install acme/data-tool --agent all",
    );
    expect(screen.getByText("Copied!")).toBeInTheDocument();

    clipboardSpy.mockRestore();
  });

  it("switches to evals tab and shows eval report", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("data-tool");

    await user.click(screen.getByText("Evals"));

    // Wait for eval report to load — look for a case result name
    await waitFor(() => {
      expect(screen.getByText("basic-case")).toBeInTheDocument();
    });
    // Check other case results are rendered
    expect(screen.getByText("edge-case")).toBeInTheDocument();
    expect(screen.getByText("fail-case")).toBeInTheDocument();
  });

  it("shows empty state when no eval report exists", async () => {
    server.use(
      http.get("/v1/skills/acme/data-tool/eval-report", () =>
        HttpResponse.json(null),
      ),
    );
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("data-tool");

    await user.click(screen.getByText("Evals"));

    await waitFor(() => {
      expect(
        screen.getByText("No evaluation report available for this version"),
      ).toBeInTheDocument();
    });
  });

  it("switches to audit tab and shows audit entries", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("data-tool");

    await user.click(screen.getByText("Audit Log"));

    // The audit entry for v2.0.0 is unique (only in audit, not sidebar)
    await waitFor(() => {
      expect(screen.getByText("v2.0.0")).toBeInTheDocument();
    });
    expect(screen.getByText(/alice@example\.com/)).toBeInTheDocument();
    expect(screen.getByText(/bob@example\.com/)).toBeInTheDocument();
  });

  it("shows check results in audit entries", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("data-tool");

    await user.click(screen.getByText("Audit Log"));

    await waitFor(() => {
      expect(screen.getByText("No shell commands found")).toBeInTheDocument();
    });
    expect(screen.getByText("No data exfiltration")).toBeInTheDocument();
  });

  it("switches to files tab", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("data-tool");

    await user.click(screen.getByText("Files"));

    // The empty zip won't have files, so we should see the empty files state
    await waitFor(() => {
      expect(
        screen.getByText(/No files to display/),
      ).toBeInTheDocument();
    });
  });

  it("renders skill-not-found when API returns 404", async () => {
    server.use(
      http.get("/v1/skills/acme/data-tool/summary", () =>
        new HttpResponse("Not found", { status: 404 }),
      ),
    );

    renderPage();

    await waitFor(() => {
      expect(
        screen.getByText(/Skill not found: acme\/data-tool/),
      ).toBeInTheDocument();
    });
  });

  it("switches between tabs maintaining overview as default", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("data-tool");

    // Overview tab should be active initially — its class includes "tabActive"
    const overviewBtn = screen.getByText("Overview").closest("button")!;
    expect(overviewBtn.className).toMatch(/tabActive/);

    // Switch to Evals
    await user.click(screen.getByText("Evals"));
    expect(screen.getByText("Evals").closest("button")!.className).toMatch(/tabActive/);
    expect(overviewBtn.className).not.toMatch(/tabActive/);

    // Switch back to Overview
    await user.click(screen.getByText("Overview"));
    expect(screen.getByText("Overview").closest("button")!.className).toMatch(/tabActive/);
  });
});
