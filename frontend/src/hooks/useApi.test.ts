import { renderHook, waitFor } from "@testing-library/react";
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

  it("resets data to null when deps change so callers don't flash stale content", async () => {
    // Simulate a route change (dep changing) between two skills. Without
    // the data-reset the previous skill's payload would render for one
    // frame while the new fetch is in flight -- exactly the class of bug
    // the "reset state on context changes" project rule targets.
    let neverResolve!: () => void;
    let currentSlug = "alpha";
    const fetcher = vi.fn(() => {
      if (currentSlug === "alpha") {
        return Promise.resolve("first-payload");
      }
      // Second call: never resolve so we can observe the intermediate
      // state after the dep flip.
      return new Promise<string>((resolve) => {
        neverResolve = () => resolve("second-payload");
      });
    });

    const { result, rerender } = renderHook(({ slug }) => useApi(fetcher, [slug]), {
      initialProps: { slug: "alpha" },
    });

    await waitFor(() => expect(result.current.data).toBe("first-payload"));

    currentSlug = "beta";
    rerender({ slug: "beta" });

    // After the dep flip, before the new fetch resolves, `data` must be
    // null -- not "first-payload".
    expect(result.current.data).toBeNull();
    expect(result.current.loading).toBe(true);

    neverResolve();
    await waitFor(() => expect(result.current.data).toBe("second-payload"));
  });
});
