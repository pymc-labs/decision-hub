import { renderHook, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRecentlyViewed, type RecentlyViewedSkill } from "./useRecentlyViewed";

const STORAGE_KEY = "dhub:recently-viewed";

// jsdom + Node 22 localStorage can be flaky — use a real Map-backed mock.
let store: Record<string, string>;
const storageMock: Storage = {
  get length() { return Object.keys(store).length; },
  key(i: number) { return Object.keys(store)[i] ?? null; },
  getItem(k: string) { return store[k] ?? null; },
  setItem(k: string, v: string) { store[k] = v; },
  removeItem(k: string) { delete store[k]; },
  clear() { store = {}; },
};

function makeSkill(overrides: Partial<RecentlyViewedSkill> = {}): RecentlyViewedSkill {
  return {
    org_slug: "acme",
    skill_name: "test-skill",
    description: "A test skill",
    safety_rating: "A",
    ...overrides,
  };
}

describe("useRecentlyViewed", () => {
  beforeEach(() => {
    store = {};
    vi.stubGlobal("localStorage", storageMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("starts empty when localStorage has no data", () => {
    const { result } = renderHook(() => useRecentlyViewed());
    expect(result.current.items).toEqual([]);
  });

  it("loads existing items from localStorage", () => {
    const existing = [makeSkill()];
    localStorage.setItem(STORAGE_KEY, JSON.stringify(existing));

    const { result } = renderHook(() => useRecentlyViewed());
    expect(result.current.items).toEqual(existing);
  });

  it("adds a skill and persists to localStorage", () => {
    const { result } = renderHook(() => useRecentlyViewed());
    const skill = makeSkill();

    act(() => result.current.addRecentlyViewed(skill));

    expect(result.current.items).toEqual([skill]);
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!)).toEqual([skill]);
  });

  it("deduplicates by org_slug + skill_name, moving to front", () => {
    const { result } = renderHook(() => useRecentlyViewed());
    const skillA = makeSkill({ org_slug: "a", skill_name: "s1", description: "old" });
    const skillB = makeSkill({ org_slug: "b", skill_name: "s2" });

    act(() => result.current.addRecentlyViewed(skillA));
    act(() => result.current.addRecentlyViewed(skillB));

    // Re-add skillA with updated description — should move to front
    const skillAUpdated = { ...skillA, description: "new" };
    act(() => result.current.addRecentlyViewed(skillAUpdated));

    expect(result.current.items).toHaveLength(2);
    expect(result.current.items[0]).toEqual(skillAUpdated);
    expect(result.current.items[1]).toEqual(skillB);
  });

  it("caps at 5 items", () => {
    const { result } = renderHook(() => useRecentlyViewed());

    for (let i = 0; i < 7; i++) {
      act(() =>
        result.current.addRecentlyViewed(
          makeSkill({ skill_name: `skill-${i}` }),
        ),
      );
    }

    expect(result.current.items).toHaveLength(5);
    // Most recent should be first
    expect(result.current.items[0].skill_name).toBe("skill-6");
    // Oldest kept should be last
    expect(result.current.items[4].skill_name).toBe("skill-2");
  });

  it("refresh() re-reads from localStorage", () => {
    const { result } = renderHook(() => useRecentlyViewed());
    expect(result.current.items).toEqual([]);

    // Simulate another component writing directly to localStorage
    const external = [makeSkill({ skill_name: "external" })];
    localStorage.setItem(STORAGE_KEY, JSON.stringify(external));

    act(() => result.current.refresh());

    expect(result.current.items).toEqual(external);
  });

  it("refresh() handles corrupted localStorage gracefully", () => {
    const { result } = renderHook(() => useRecentlyViewed());
    localStorage.setItem(STORAGE_KEY, "not-json!!!");

    act(() => result.current.refresh());

    expect(result.current.items).toEqual([]);
  });
});
