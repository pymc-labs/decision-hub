import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { useApi } from "./useApi";

describe("useApi", () => {
  it("starts with loading=true, data=null, error=null, errorStatus=null", () => {
    const fetcher = vi.fn(() => new Promise<string>(() => {})); // never resolves
    const { result } = renderHook(() => useApi(fetcher));

    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.errorStatus).toBeNull();
  });

  it("resolves to data on success", async () => {
    const fetcher = vi.fn(() => Promise.resolve("hello"));
    const { result } = renderHook(() => useApi(fetcher));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.data).toBe("hello");
    expect(result.current.error).toBeNull();
    expect(result.current.errorStatus).toBeNull();
  });

  it("captures error message on plain Error failure", async () => {
    const fetcher = vi.fn(() => Promise.reject(new Error("network down")));
    const { result } = renderHook(() => useApi(fetcher));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.data).toBeNull();
    expect(result.current.error).toBe("network down");
    expect(result.current.errorStatus).toBeNull();
  });

  it("captures HTTP status when the rejection is an ApiError", async () => {
    const err = new ApiError(404, "Not found");
    const fetcher = vi.fn(() => Promise.reject(err));
    const { result } = renderHook(() => useApi(fetcher));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe("Not found");
    expect(result.current.errorStatus).toBe(404);
  });

  it("refetch() resets loading and re-fetches", async () => {
    let callCount = 0;
    const fetcher = vi.fn(() => Promise.resolve(`call-${++callCount}`));
    const { result } = renderHook(() => useApi(fetcher));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toBe("call-1");

    act(() => result.current.refetch());

    await waitFor(() => expect(result.current.data).toBe("call-2"));
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("drops stale results when two refetch() calls overlap", async () => {
    // Two slow promises. We resolve the SECOND one first, then the
    // FIRST. Without staleness handling, the first (older) result
    // would clobber the newer one.
    let resolveA: (v: string) => void = () => {};
    let resolveB: (v: string) => void = () => {};
    const fetcher = vi
      .fn()
      .mockImplementationOnce(() => new Promise<string>((res) => { resolveA = res; }))
      .mockImplementationOnce(() => new Promise<string>((res) => { resolveB = res; }))
      .mockImplementationOnce(() => new Promise<string>((res) => { resolveB = res; }));

    const { result } = renderHook(() => useApi(fetcher));

    // Mount fires fetch #1. Trigger fetch #2 before #1 resolves.
    act(() => result.current.refetch());

    // Resolve #2 first — that's the one we expect to win.
    resolveB("newer");
    await waitFor(() => expect(result.current.data).toBe("newer"));

    // Now resolve the stale #1. It MUST be ignored.
    resolveA("older");
    // Give the microtask queue a chance to settle.
    await Promise.resolve();
    expect(result.current.data).toBe("newer");
  });

  it("drops stale results when refetch() races with a deps change", async () => {
    let resolveFirst: (v: string) => void = () => {};
    let resolveSecond: (v: string) => void = () => {};
    const fetcher = vi
      .fn()
      .mockImplementationOnce(() => new Promise<string>((res) => { resolveFirst = res; }))
      .mockImplementationOnce(() => new Promise<string>((res) => { resolveSecond = res; }));

    let dep = 1;
    const { result, rerender } = renderHook(({ d }) => useApi(fetcher, [d]), {
      initialProps: { d: dep },
    });

    // Bump deps — should trigger a new fetch, leaving the first stale.
    dep = 2;
    rerender({ d: dep });

    // Resolve the newer fetch first.
    resolveSecond("v2");
    await waitFor(() => expect(result.current.data).toBe("v2"));

    // Stale resolution must not overwrite.
    resolveFirst("v1");
    await Promise.resolve();
    expect(result.current.data).toBe("v2");
  });
});
