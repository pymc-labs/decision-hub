import { describe, expect, it } from "vitest";
import type { SkillSummary } from "../types/api";
import {
  extractOrgs,
  filterSkills,
  aggregateOrgs,
  filterOrgs,
} from "./filters";

function makeSkill(overrides: Partial<SkillSummary> = {}): SkillSummary {
  return {
    org_slug: "acme",
    skill_name: "test-skill",
    description: "A test skill",
    latest_version: "1.0.0",
    updated_at: "2025-01-01T00:00:00Z",
    safety_rating: "A-Safe",
    author: "dev",
    download_count: 10,
    is_personal_org: false,
    category: "",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// extractOrgs
// ---------------------------------------------------------------------------

describe("extractOrgs", () => {
  it("returns empty array for empty input", () => {
    expect(extractOrgs([])).toEqual([]);
  });

  it("deduplicates org slugs", () => {
    const skills = [
      makeSkill({ org_slug: "acme" }),
      makeSkill({ org_slug: "acme" }),
      makeSkill({ org_slug: "beta" }),
    ];
    expect(extractOrgs(skills)).toEqual(["acme", "beta"]);
  });

  it("sorts alphabetically", () => {
    const skills = [
      makeSkill({ org_slug: "zebra" }),
      makeSkill({ org_slug: "alpha" }),
      makeSkill({ org_slug: "middle" }),
    ];
    expect(extractOrgs(skills)).toEqual(["alpha", "middle", "zebra"]);
  });
});

// ---------------------------------------------------------------------------
// filterSkills
// ---------------------------------------------------------------------------

describe("filterSkills", () => {
  const skills = [
    makeSkill({
      org_slug: "acme",
      skill_name: "deploy-bot",
      description: "Deploys stuff",
      safety_rating: "A-Safe",
      download_count: 100,
      updated_at: "2025-03-01T00:00:00Z",
    }),
    makeSkill({
      org_slug: "beta",
      skill_name: "code-review",
      description: "Reviews code",
      safety_rating: "B-Elevated",
      download_count: 50,
      updated_at: "2025-02-01T00:00:00Z",
    }),
    makeSkill({
      org_slug: "acme",
      skill_name: "lint-fix",
      description: "Fixes lint issues",
      safety_rating: "C-Risky",
      download_count: 200,
      updated_at: "2025-01-01T00:00:00Z",
    }),
  ];

  it("returns all skills with no filters", () => {
    const result = filterSkills(skills, "", "all", "all", "updated");
    expect(result).toHaveLength(3);
  });

  it("searches by skill name (case-insensitive)", () => {
    const result = filterSkills(skills, "DEPLOY", "all", "all", "name");
    expect(result).toHaveLength(1);
    expect(result[0].skill_name).toBe("deploy-bot");
  });

  it("searches by description", () => {
    const result = filterSkills(skills, "reviews", "all", "all", "name");
    expect(result).toHaveLength(1);
    expect(result[0].skill_name).toBe("code-review");
  });

  it("searches by org slug", () => {
    const result = filterSkills(skills, "beta", "all", "all", "name");
    expect(result).toHaveLength(1);
    expect(result[0].org_slug).toBe("beta");
  });

  it("filters by org", () => {
    const result = filterSkills(skills, "", "acme", "all", "name");
    expect(result).toHaveLength(2);
    expect(result.every((s) => s.org_slug === "acme")).toBe(true);
  });

  it("filters by grade with startsWith", () => {
    const result = filterSkills(skills, "", "all", "B", "name");
    expect(result).toHaveLength(1);
    expect(result[0].safety_rating).toBe("B-Elevated");
  });

  it("sorts by name", () => {
    const result = filterSkills(skills, "", "all", "all", "name");
    expect(result.map((s) => s.skill_name)).toEqual([
      "code-review",
      "deploy-bot",
      "lint-fix",
    ]);
  });

  it("sorts by downloads descending", () => {
    const result = filterSkills(skills, "", "all", "all", "downloads");
    expect(result.map((s) => s.download_count)).toEqual([200, 100, 50]);
  });

  it("sorts by updated descending (default)", () => {
    const result = filterSkills(skills, "", "all", "all", "updated");
    expect(result.map((s) => s.skill_name)).toEqual([
      "deploy-bot",
      "code-review",
      "lint-fix",
    ]);
  });

  it("combines search + org + grade filters", () => {
    const result = filterSkills(skills, "fix", "acme", "C", "name");
    expect(result).toHaveLength(1);
    expect(result[0].skill_name).toBe("lint-fix");
  });

  it("filters by category", () => {
    const categorized = [
      makeSkill({ skill_name: "api-gen", category: "Backend & APIs" }),
      makeSkill({ skill_name: "llm-tool", category: "AI & LLM" }),
      makeSkill({ skill_name: "cli-help", category: "Backend & APIs" }),
    ];
    const result = filterSkills(categorized, "", "all", "all", "name", "Backend & APIs");
    expect(result).toHaveLength(2);
    expect(result.map((s) => s.skill_name)).toEqual(["api-gen", "cli-help"]);
  });

  it("returns all when categoryFilter is 'all'", () => {
    const categorized = [
      makeSkill({ skill_name: "a", category: "AI & LLM" }),
      makeSkill({ skill_name: "b", category: "Backend & APIs" }),
    ];
    const result = filterSkills(categorized, "", "all", "all", "name", "all");
    expect(result).toHaveLength(2);
  });

  it("returns empty when no skills match category", () => {
    const categorized = [
      makeSkill({ skill_name: "a", category: "AI & LLM" }),
    ];
    const result = filterSkills(categorized, "", "all", "all", "name", "Backend & APIs");
    expect(result).toHaveLength(0);
  });

  it("combines category with search and org filters", () => {
    const categorized = [
      makeSkill({ org_slug: "acme", skill_name: "deploy-api", category: "Backend & APIs" }),
      makeSkill({ org_slug: "acme", skill_name: "deploy-ui", category: "Frontend & UI" }),
      makeSkill({ org_slug: "beta", skill_name: "api-lint", category: "Backend & APIs" }),
    ];
    const result = filterSkills(categorized, "deploy", "acme", "all", "name", "Backend & APIs");
    expect(result).toHaveLength(1);
    expect(result[0].skill_name).toBe("deploy-api");
  });
});

// ---------------------------------------------------------------------------
// aggregateOrgs
// ---------------------------------------------------------------------------

describe("aggregateOrgs", () => {
  it("returns empty array for empty input", () => {
    expect(aggregateOrgs([])).toEqual([]);
  });

  it("aggregates skills per org", () => {
    const skills = [
      makeSkill({
        org_slug: "acme",
        download_count: 10,
        updated_at: "2025-01-01T00:00:00Z",
        is_personal_org: false,
      }),
      makeSkill({
        org_slug: "acme",
        download_count: 20,
        updated_at: "2025-03-01T00:00:00Z",
        is_personal_org: false,
      }),
      makeSkill({
        org_slug: "bob",
        download_count: 5,
        updated_at: "2025-02-01T00:00:00Z",
        is_personal_org: true,
      }),
    ];

    const result = aggregateOrgs(skills);
    expect(result).toHaveLength(2);

    const acme = result.find((o) => o.slug === "acme")!;
    expect(acme.skillCount).toBe(2);
    expect(acme.totalDownloads).toBe(30);
    expect(acme.latestUpdate).toBe("2025-03-01T00:00:00Z");
    expect(acme.isPersonal).toBe(false);

    const bob = result.find((o) => o.slug === "bob")!;
    expect(bob.skillCount).toBe(1);
    expect(bob.totalDownloads).toBe(5);
    expect(bob.isPersonal).toBe(true);
  });

  it("sorts orgs alphabetically", () => {
    const skills = [
      makeSkill({ org_slug: "zebra" }),
      makeSkill({ org_slug: "alpha" }),
    ];
    const result = aggregateOrgs(skills);
    expect(result.map((o) => o.slug)).toEqual(["alpha", "zebra"]);
  });
});

// ---------------------------------------------------------------------------
// filterOrgs
// ---------------------------------------------------------------------------

describe("filterOrgs", () => {
  const orgs = [
    {
      slug: "acme-corp",
      skillCount: 5,
      totalDownloads: 100,
      latestUpdate: "2025-01-01T00:00:00Z",
      isPersonal: false,
    },
    {
      slug: "bob",
      skillCount: 2,
      totalDownloads: 30,
      latestUpdate: "2025-02-01T00:00:00Z",
      isPersonal: true,
    },
    {
      slug: "dev-team",
      skillCount: 3,
      totalDownloads: 50,
      latestUpdate: "2025-03-01T00:00:00Z",
      isPersonal: false,
    },
  ];

  it("returns all orgs with no filters", () => {
    expect(filterOrgs(orgs, "", "all")).toHaveLength(3);
  });

  it("filters by search (case-insensitive)", () => {
    const result = filterOrgs(orgs, "ACME", "all");
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe("acme-corp");
  });

  it("filters type=orgs to exclude personal", () => {
    const result = filterOrgs(orgs, "", "orgs");
    expect(result).toHaveLength(2);
    expect(result.every((o) => !o.isPersonal)).toBe(true);
  });

  it("filters type=users to only personal", () => {
    const result = filterOrgs(orgs, "", "users");
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe("bob");
  });

  it("combines search and type filter", () => {
    const result = filterOrgs(orgs, "dev", "orgs");
    expect(result).toHaveLength(1);
    expect(result[0].slug).toBe("dev-team");
  });
});
