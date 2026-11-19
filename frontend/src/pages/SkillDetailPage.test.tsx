import { act, screen, waitFor, within } from "@testing-library/react";
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
import * as api from "../api/client";
import * as featureFlags from "../featureFlags";
import type { PaginatedAuditLogResponse } from "../types/api";

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

// The endpoint returns 20 newest-first entries by default. Page two contains
// the oldest entry, which makes the server total distinct from either page size.
function auditPage(page: number): PaginatedAuditLogResponse {
  const entries = Array.from({ length: 21 }, (_, index) => makeAuditLogEntry({
    id: `audit-${index}`,
    publisher: `publisher-${21 - index}`,
    check_results: [],
  }));
  return { items: entries.slice((page - 1) * 20, page * 20), page, total: 21, page_size: 20, total_pages: 2 };
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
    expect(screen.queryByRole("link", { name: "Cisco Skill Scanner" })).not.toBeInTheDocument();
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

  it("pages through audit history by keyboard and retries the failed page", async () => {
    const requests: number[] = [];
    server.use(http.get("/v1/skills/acme/data-tool/audit-log", ({ request }) => {
      const page = Number(new URL(request.url).searchParams.get("page") ?? 1);
      if (page === 2 && !requests.includes(2)) {
        requests.push(page);
        return new HttpResponse(null, { status: 503 });
      }
      requests.push(page);
      return HttpResponse.json(auditPage(page));
    }));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Audit Log" }));

    const nav = within(await screen.findByRole("navigation", { name: "Audit history pages" }));
    const previous = nav.getByRole("button", { name: "Previous page" });
    const next = nav.getByRole("button", { name: "Next page" });
    expect(previous).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("21 audit entries · Page 1 of 2");
    next.focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not load audit page 2/i);
    expect(screen.getByRole("status")).toHaveTextContent("Page 1 of 2");
    expect(screen.getByText("by publisher-21")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("by publisher-1");
    expect(screen.getByRole("status")).toHaveTextContent("21 audit entries · Page 2 of 2");
    expect(next).toBeDisabled();
    expect(screen.queryByText("by publisher-21")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await user.click(previous);
    await screen.findByText("by publisher-21");
    expect(previous).toBeDisabled();
    expect(requests).toEqual([1, 2, 2, 1]);
  });

  it("can return to the remaining page if older entries disappear between requests", async () => {
    const firstPage = auditPage(1);
    server.use(http.get("/v1/skills/acme/data-tool/audit-log", ({ request }) => {
      const page = Number(new URL(request.url).searchParams.get("page"));
      if (page === 1) return HttpResponse.json(firstPage);
      firstPage.total = 20;
      firstPage.total_pages = 1;
      return HttpResponse.json({ ...firstPage, page, items: [] });
    }));
    const user = userEvent.setup();
    renderPage();
    await user.click(await screen.findByRole("button", { name: "Audit Log" }));
    await user.click(await screen.findByRole("button", { name: "Next page" }));
    await screen.findByText(/Page 2 is no longer available/);
    await user.click(screen.getByRole("button", { name: "Previous page" }));
    await screen.findByText("by publisher-21");
    expect(screen.getByRole("status")).toHaveTextContent("20 audit entries · Page 1 of 1");
  });

  it("starts the next skill at page one and ignores a late page from the previous skill", async () => {
    let finishOldPage!: (page: PaginatedAuditLogResponse) => void;
    const oldPage = new Promise<PaginatedAuditLogResponse>((resolve) => { finishOldPage = resolve; });
    const requests: [string, number][] = [];
    const fetchAudit = vi.spyOn(api, "getAuditLog").mockImplementation((org, _skill, _semver, page = 1) => {
      requests.push([org, page]);
      if (org === "acme") return page === 1 ? Promise.resolve(auditPage(1)) : oldPage;
      return Promise.resolve({ items: [], total: 0, page, page_size: 20, total_pages: 1 });
    });
    server.use(
      http.get("/v1/skills/acme/data-tool/similar", () => HttpResponse.json([{ ...SKILL, org_slug: "other" }])),
      http.get("/v1/skills/other/data-tool/summary", () => HttpResponse.json({ ...SKILL, org_slug: "other" })),
      http.get("/v1/skills/other/data-tool/eval-report", () => HttpResponse.json(null)),
      http.get("/v1/skills/other/data-tool/similar", () => HttpResponse.json([])),
    );
    try {
      const user = userEvent.setup();
      renderPage();
      await user.click(await screen.findByRole("button", { name: "Audit Log" }));
      await user.click(await screen.findByRole("button", { name: "Next page" }));
      await waitFor(() => expect(requests).toContainEqual(["acme", 2]));
      await user.click(screen.getByRole("link", { name: /other\/data-tool/ }));
      await screen.findByText("No audit log entries found");
      await act(async () => { finishOldPage(auditPage(2)); });

      expect(requests).toEqual([["acme", 1], ["acme", 2], ["other", 1]]);
      expect(screen.getByText("No audit log entries found")).toBeInTheDocument();
      expect(screen.queryByText("by publisher-1")).not.toBeInTheDocument();
      expect(screen.queryByRole("navigation", { name: "Audit history pages" })).not.toBeInTheDocument();
    } finally {
      fetchAudit.mockRestore();
    }
  });

  it("keeps the enabled scanner visible when the first audit page fails and retries to empty history", async () => {
    const flags: { SHOW_SCANNER_REPORT: boolean } = featureFlags;
    const scannerFlag = vi.spyOn(flags, "SHOW_SCANNER_REPORT", "get").mockReturnValue(true);
    server.use(
      http.get("/v1/skills/acme/data-tool/scan-report", () => HttpResponse.json({
        max_severity: "SAFE", findings: [], analyzers_used: ["static"],
      })),
      http.get("/v1/skills/acme/data-tool/audit-log", () =>
        new HttpResponse(null, { status: 503 }), { once: true }),
      http.get("/v1/skills/acme/data-tool/audit-log", () =>
        HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20, total_pages: 1 })),
    );
    try {
      const user = userEvent.setup();
      renderPage();
      await user.click(await screen.findByRole("button", { name: "Audit Log" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(/could not load audit page 1/i);
      const scanner = await screen.findByRole("link", { name: "Cisco Skill Scanner" });
      expect(screen.queryByText("No audit log entries found")).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Retry" }));
      await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
      expect(await screen.findByText("No audit log entries found")).toBeInTheDocument();
      expect(scanner).toBeInTheDocument();
    } finally {
      scannerFlag.mockRestore();
    }
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

  it("surfaces a visible error banner when the download API 500s", async () => {
    // Override the /download handler to return a server error.
    server.use(
      http.get("/v1/skills/acme/data-tool/download", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    const user = userEvent.setup();
    renderPage();
    await screen.findByText("data-tool");

    // Sanity: no error visible yet.
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await user.click(screen.getByText("Download .zip"));

    // The failure previously only printed to console.error — the button
    // flipped back to enabled and the user got no feedback. Now we render
    // a role="alert" banner with the failure message.
    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toBeInTheDocument();
      expect(alert.textContent).toMatch(/Download failed/i);
    });
  });
});

it("does not offer the previous skill's details or install action when a linked skill disappears", async () => {
  server.use(
    http.get("/v1/skills/acme/data-tool/similar", () =>
      HttpResponse.json([{ ...SKILL, org_slug: "retired" }]),
    ),
    http.get("/v1/skills/retired/data-tool/summary", () => new HttpResponse(null, { status: 404 })),
    http.get("/v1/skills/retired/data-tool/similar", () => HttpResponse.json([])),
    http.get("/v1/skills/retired/data-tool/eval-report", () => HttpResponse.json(null)),
    http.get("/v1/skills/retired/data-tool/download", () => new HttpResponse(EMPTY_ZIP)),
  );
  const user = userEvent.setup();
  renderPage();
  await user.click(await screen.findByRole("link", { name: /retired\/data-tool/ }));
  expect(await screen.findByText("Skill not found: retired/data-tool")).toBeInTheDocument();
  expect(screen.queryByText("Analyzes datasets")).not.toBeInTheDocument();
  expect(screen.queryByText(/dhub install/)).not.toBeInTheDocument();
});
