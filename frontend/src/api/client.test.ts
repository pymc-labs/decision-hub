import { delay, http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import {
  ApiError,
  listSkillsFiltered,
  getSkill,
  getRegistryStats,
  listOrgStats,
  resolveSkill,
  getEvalReport,
  getAuditLog,
  downloadSkillZip,
} from "./client";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("listSkillsFiltered", () => {
  it("returns paginated response with default params", async () => {
    const response = {
      items: [
        { org_slug: "acme", skill_name: "test-skill", download_count: 42 },
      ],
      total: 1,
      page: 1,
      page_size: 20,
      total_pages: 1,
    };
    server.use(
      http.get("/v1/skills", () => HttpResponse.json(response)),
    );

    const result = await listSkillsFiltered();
    expect(result).toEqual(response);
    expect(result.items).toHaveLength(1);
  });

  it("passes filter params as query string", async () => {
    const response = {
      items: [],
      total: 0,
      page: 1,
      page_size: 12,
      total_pages: 1,
    };
    server.use(
      http.get("/v1/skills", ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.get("page")).toBe("2");
        expect(url.searchParams.get("page_size")).toBe("12");
        expect(url.searchParams.get("search")).toBe("deploy");
        expect(url.searchParams.get("org")).toBe("acme");
        expect(url.searchParams.get("grade")).toBe("A");
        expect(url.searchParams.get("sort")).toBe("downloads");
        return HttpResponse.json(response);
      }),
    );

    await listSkillsFiltered({
      page: 2,
      pageSize: 12,
      search: "deploy",
      org: "acme",
      grade: "A",
      sort: "downloads",
    });
  });

  it("omits empty filter params from query string", async () => {
    const response = {
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
      total_pages: 1,
    };
    server.use(
      http.get("/v1/skills", ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.has("search")).toBe(false);
        expect(url.searchParams.has("org")).toBe(false);
        expect(url.searchParams.has("category")).toBe(false);
        expect(url.searchParams.has("grade")).toBe(false);
        return HttpResponse.json(response);
      }),
    );

    await listSkillsFiltered();
  });
});

describe("getSkill", () => {
  it("returns a single skill summary", async () => {
    const skill = {
      org_slug: "acme",
      skill_name: "my-skill",
      description: "A skill",
      latest_version: "1.0.0",
    };
    server.use(
      http.get("/v1/skills/:org/:skill/summary", () =>
        HttpResponse.json(skill),
      ),
    );

    const result = await getSkill("acme", "my-skill");
    expect(result).toEqual(skill);
  });
});

describe("getRegistryStats", () => {
  it("returns registry statistics", async () => {
    const stats = { total_skills: 100, total_orgs: 10, total_downloads: 5000, active_categories: ["Code Generation"] };
    server.use(
      http.get("/v1/stats", () => HttpResponse.json(stats)),
    );

    const result = await getRegistryStats();
    expect(result).toEqual(stats);
  });
});

describe("listOrgStats", () => {
  it("returns org statistics with filters", async () => {
    const response = {
      items: [{ slug: "acme", skill_count: 5, total_downloads: 100 }],
    };
    server.use(
      http.get("/v1/orgs/stats", ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.get("search")).toBe("acme");
        expect(url.searchParams.get("type_filter")).toBe("orgs");
        return HttpResponse.json(response);
      }),
    );

    const result = await listOrgStats({ search: "acme", typeFilter: "orgs" });
    expect(result.items).toHaveLength(1);
  });
});

describe("resolveSkill", () => {
  it("encodes query params correctly", async () => {
    const response = {
      version: "1.0.0",
      download_url: "https://example.com/dl",
      checksum: "abc123",
    };
    server.use(
      http.get("/v1/resolve/:org/:skill", ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.get("spec")).toBe(">=1.0");
        expect(url.searchParams.get("allow_risky")).toBe("false");
        return HttpResponse.json(response);
      }),
    );

    const result = await resolveSkill("acme", "my-skill", ">=1.0", false);
    expect(result).toEqual(response);
  });
});

describe("getEvalReport", () => {
  it("returns null when body is null", async () => {
    server.use(
      http.get("/v1/skills/:org/:skill/eval-report", () =>
        HttpResponse.json(null),
      ),
    );

    const result = await getEvalReport("acme", "my-skill", "1.0.0");
    expect(result).toBeNull();
  });

  it("returns eval report on success", async () => {
    const report = { id: "r1", status: "completed", passed: 3, total: 4 };
    server.use(
      http.get("/v1/skills/:org/:skill/eval-report", () =>
        HttpResponse.json(report),
      ),
    );

    const result = await getEvalReport("acme", "my-skill", "1.0.0");
    expect(result).toEqual(report);
  });
});

describe("getAuditLog", () => {
  it("calls without semver param when not provided", async () => {
    const response = { items: [{ id: "a1", grade: "A" }], total: 1, page: 1, page_size: 20, total_pages: 1 };
    server.use(
      http.get("/v1/skills/:org/:skill/audit-log", ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.has("semver")).toBe(false);
        return HttpResponse.json(response);
      }),
    );

    const result = await getAuditLog("acme", "my-skill");
    expect(result).toEqual(response);
  });

  it("includes semver param when provided", async () => {
    const response = { items: [{ id: "a1", grade: "B" }], total: 1, page: 1, page_size: 20, total_pages: 1 };
    server.use(
      http.get("/v1/skills/:org/:skill/audit-log", ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.get("semver")).toBe("2.0.0");
        return HttpResponse.json(response);
      }),
    );

    const result = await getAuditLog("acme", "my-skill", "2.0.0");
    expect(result).toEqual(response);
  });
});

describe("downloadSkillZip", () => {
  it("returns ArrayBuffer", async () => {
    const bytes = new Uint8Array([80, 75, 3, 4]); // ZIP magic bytes
    server.use(
      http.get("/v1/skills/:org/:skill/download", () =>
        new HttpResponse(bytes, {
          headers: { "Content-Type": "application/zip" },
        }),
      ),
    );

    const result = await downloadSkillZip("acme", "my-skill");
    expect(result).toBeInstanceOf(ArrayBuffer);
    expect(new Uint8Array(result)).toEqual(bytes);
  });
});

describe("error handling", () => {
  it("throws ApiError with status on plain-text non-OK response", async () => {
    server.use(
      http.get("/v1/skills", () =>
        new HttpResponse("Internal Server Error", {
          status: 500,
          headers: { "Content-Type": "text/plain" },
        }),
      ),
    );

    await expect(listSkillsFiltered()).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
      message: "Internal Server Error",
    });
  });

  it("extracts FastAPI {detail} message from JSON error bodies", async () => {
    server.use(
      http.get("/v1/skills", () =>
        HttpResponse.json({ detail: "Rate limit exceeded" }, { status: 429 }),
      ),
    );

    await expect(listSkillsFiltered()).rejects.toMatchObject({
      name: "ApiError",
      status: 429,
      message: "Rate limit exceeded",
      body: { detail: "Rate limit exceeded" },
    });
  });

  it("never leaks raw HTML bodies into the user-facing message", async () => {
    const html =
      "<html><head><title>502</title></head><body><h1>Bad Gateway</h1></body></html>";
    server.use(
      http.get("/v1/skills", () =>
        new HttpResponse(html, {
          status: 502,
          headers: { "Content-Type": "text/html" },
        }),
      ),
    );

    try {
      await listSkillsFiltered();
      throw new Error("expected ApiError to be thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(502);
      // The user-facing message must not contain any HTML.
      expect(apiErr.message).not.toContain("<");
      expect(apiErr.message).toMatch(/502/);
      // The raw body is still attached for debug surfaces.
      expect(apiErr.body).toBe(html);
    }
  });

  it("treats summary FastAPI validation errors as a one-line message", async () => {
    server.use(
      http.get("/v1/skills", () =>
        HttpResponse.json(
          {
            detail: [
              { loc: ["query", "page"], msg: "field required", type: "missing" },
              { loc: ["query", "sort"], msg: "string does not match regex", type: "value_error" },
            ],
          },
          { status: 422 },
        ),
      ),
    );

    await expect(listSkillsFiltered()).rejects.toMatchObject({
      name: "ApiError",
      status: 422,
      message: "Validation failed (2 issues).",
    });
  });

  it("aborts and throws ApiError(status=0) on timeout", async () => {
    server.use(
      http.get("/v1/skills", async () => {
        // Hold the response open longer than the test's timeout below.
        await delay(200);
        return HttpResponse.json({
          items: [],
          total: 0,
          page: 1,
          page_size: 20,
          total_pages: 1,
        });
      }),
    );

    // listSkillsFiltered() always uses the default 30s, so call the
    // public API surface but also exercise the timeout path on a
    // dedicated request — listSkillsFiltered's params don't include a
    // timeout override, so we run a direct fetch through the same
    // function by overriding it via listSkillsFiltered fallback below.
    // Use downloadSkillZip's exposed timeoutMs argument instead.
    server.use(
      http.get("/v1/skills/:org/:skill/download", async () => {
        await delay(200);
        return new HttpResponse(new Uint8Array([0]));
      }),
    );

    await expect(downloadSkillZip("acme", "skill", "latest", false, 25))
      .rejects.toMatchObject({
        name: "ApiError",
        status: 0,
        message: expect.stringMatching(/timed out/i),
      });
  });

  it("throws ApiError on download failure", async () => {
    server.use(
      http.get("/v1/skills/:org/:skill/download", () =>
        new HttpResponse(null, { status: 404 }),
      ),
    );

    await expect(downloadSkillZip("acme", "my-skill")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      message: "Download failed (404).",
    });
  });
});
