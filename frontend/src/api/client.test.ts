import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";
import {
  listSkills,
  resolveSkill,
  getEvalReport,
  getAuditLog,
  downloadSkillZip,
} from "./client";

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("listSkills", () => {
  it("returns parsed JSON array", async () => {
    const skills = [
      { org_slug: "acme", skill_name: "test-skill", download_count: 42 },
    ];
    server.use(
      http.get("/v1/skills", () => HttpResponse.json(skills)),
    );

    const result = await listSkills();
    expect(result).toEqual(skills);
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
    const entries = [{ id: "a1", grade: "A" }];
    server.use(
      http.get("/v1/skills/:org/:skill/audit-log", ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.has("semver")).toBe(false);
        return HttpResponse.json(entries);
      }),
    );

    const result = await getAuditLog("acme", "my-skill");
    expect(result).toEqual(entries);
  });

  it("includes semver param when provided", async () => {
    const entries = [{ id: "a1", grade: "B" }];
    server.use(
      http.get("/v1/skills/:org/:skill/audit-log", ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.get("semver")).toBe("2.0.0");
        return HttpResponse.json(entries);
      }),
    );

    const result = await getAuditLog("acme", "my-skill", "2.0.0");
    expect(result).toEqual(entries);
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
  it("throws with status and body on non-OK response", async () => {
    server.use(
      http.get("/v1/skills", () =>
        new HttpResponse("Internal Server Error", { status: 500 }),
      ),
    );

    await expect(listSkills()).rejects.toThrow("API 500: Internal Server Error");
  });

  it("throws on download failure", async () => {
    server.use(
      http.get("/v1/skills/:org/:skill/download", () =>
        new HttpResponse(null, { status: 404 }),
      ),
    );

    await expect(downloadSkillZip("acme", "my-skill")).rejects.toThrow(
      "Download failed: 404",
    );
  });
});
