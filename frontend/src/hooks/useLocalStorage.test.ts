import { renderHook, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useLocalStorage } from "./useLocalStorage";

// Map-backed localStorage stub — jsdom's is flaky under Node 22 in the
// same way `useRecentlyViewed.test.ts` documents.
let store: Record<string, string>;
const storageMock: Storage = {
  get length() {
    return Object.keys(store).length;
  },
  key(i: number) {
    return Object.keys(store)[i] ?? null;
  },
  getItem(k: string) {
    return store[k] ?? null;
  },
  setItem(k: string, v: string) {
    store[k] = v;
  },
  removeItem(k: string) {
    delete store[k];
  },
  clear() {
    store = {};
  },
};

describe("useLocalStorage", () => {
  beforeEach(() => {
    store = {};
    vi.stubGlobal("localStorage", storageMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the initial value when localStorage is empty", () => {
    const { result } = renderHook(() => useLocalStorage("k", "fallback"));
    expect(result.current[0]).toBe("fallback");
  });

  it("reads and JSON-parses an existing value", () => {
    localStorage.setItem("k", JSON.stringify({ n: 42 }));
    const { result } = renderHook(() =>
      useLocalStorage<{ n: number }>("k", { n: 0 }),
    );
    expect(result.current[0]).toEqual({ n: 42 });
  });

  it("falls back to initial when the stored value is corrupt JSON", () => {
    // Regression: a hand-edited or half-written localStorage entry
    // used to crash the whole page with SyntaxError. The initializer
    // must swallow parse errors and hand back the caller's fallback.
    localStorage.setItem("k", "not-json{{{");
    const { result } = renderHook(() => useLocalStorage("k", "default"));
    expect(result.current[0]).toBe("default");
  });

  it("setter persists the new value and updates state", () => {
    const { result } = renderHook(() => useLocalStorage<number>("k", 0));

    act(() => result.current[1](7));

    expect(result.current[0]).toBe(7);
    expect(JSON.parse(localStorage.getItem("k")!)).toBe(7);
  });

  it("setter supports the (prev) => next functional form", () => {
    const { result } = renderHook(() => useLocalStorage<number>("k", 10));

    act(() => result.current[1]((prev) => prev + 5));

    expect(result.current[0]).toBe(15);
    expect(JSON.parse(localStorage.getItem("k")!)).toBe(15);
  });

  it("survives a localStorage quota error without throwing", () => {
    // Some browsers throw QuotaExceededError on setItem when the tab's
    // storage budget is full (Safari private mode is the classic case).
    // The hook must swallow the error so the UI keeps rendering — the
    // value still lives in React state even if it can't be persisted.
    const setItem = vi.fn(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });
    vi.stubGlobal("localStorage", { ...storageMock, setItem });

    const { result } = renderHook(() => useLocalStorage<string>("k", "a"));

    expect(() => act(() => result.current[1]("b"))).not.toThrow();
    expect(result.current[0]).toBe("b");
  });
});
