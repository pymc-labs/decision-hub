import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useApi } from "./useApi";

describe("useApi", () => {
  it("starts with loading=true, data=null, error=null", () => {
    const fetcher = vi.fn(() => new Promise<string>(() => {})); // never resolves
    const { result } = renderHook(() => useApi(fetcher));

    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("resolves to data on success", async () => {
    const fetcher = vi.fn(() => Promise.resolve("hello"));
    const { result } = renderHook(() => useApi(fetcher));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.data).toBe("hello");
    expect(result.current.error).toBeNull();
  });

  it("captures error message on failure", async () => {
    const fetcher = vi.fn(() => Promise.reject(new Error("network down")));
    const { result } = renderHook(() => useApi(fetcher));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.data).toBeNull();
    expect(result.current.error).toBe("network down");
  });

  it("refetch() resets loading and re-fetches", async () => {
    let callCount = 0;
    const fetcher = vi.fn(() => Promise.resolve(`call-${++callCount}`));
    const { result } = renderHook(() => useApi(fetcher));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toBe("call-1");

    result.current.refetch();

    await waitFor(() => expect(result.current.data).toBe("call-2"));
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("stale refetch cannot overwrite a newer response", async () => {
    // Regression: previously the refetch path had no staleness guard,
    // so a slow refetch could land after a fresher fetch and roll data
    // back to the stale value. See useApi.ts for the fetchIdRef guard.
    const resolvers: Array<(v: string) => void> = [];
    let call = 0;
    const fetcher = vi.fn(
      () =>
        new Promise<string>((resolve) => {
          call += 1;
          const myCall = call;
          resolvers.push(() => resolve(`call-${myCall}`));
        })
    );

    const { result } = renderHook(() => useApi(fetcher));

    // Kick off refetch (2nd in-flight call) while the first is still pending.
    act(() => {
      result.current.refetch();
    });

    expect(resolvers.length).toBe(2);
    // Resolve the newest fetch first with the fresh value...
    act(() => resolvers[1]("fresh"));
    await waitFor(() => expect(result.current.data).toBe("call-2"));
    // ...then let the older fetch complete late. It must NOT overwrite.
    act(() => resolvers[0]("stale"));
    // Give the microtask a chance to run; data must stay fresh.
    await Promise.resolve();
    expect(result.current.data).toBe("call-2");
  });
});
