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

    await act(async () => {
      result.current.refetch();
    });

    await waitFor(() => expect(result.current.data).toBe("call-2"));
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it("refetch() ignores an older in-flight response when called again", async () => {
    // Regression: two rapid refetch()es (double-clicked retry button, or
    // refetch() followed by a deps-driven reload) used to let whichever
    // Promise resolved LAST win — usually the slower first one — so the
    // UI silently showed stale data. Both calls must be tagged and only
    // the most recent may write to state.
    const resolvers: Array<(v: string) => void> = [];
    const fetcher = vi.fn(
      () => new Promise<string>((resolve) => resolvers.push(resolve)),
    );
    const { result } = renderHook(() => useApi(fetcher));

    // Wait for the mount effect to actually invoke the fetcher, then
    // settle it — the race we care about is between the two subsequent
    // refetch()es, not the mount fetch.
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    await act(async () => {
      resolvers[0]("initial");
    });
    expect(result.current.data).toBe("initial");

    // Two refetches in quick succession.
    act(() => {
      result.current.refetch();
      result.current.refetch();
    });
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));

    // Resolve them in REVERSE order so the older refetch lands last.
    await act(async () => {
      resolvers[2]("newer");
      resolvers[1]("older");
    });

    // The newer refetch must win, not whichever resolved last.
    expect(result.current.data).toBe("newer");
    expect(result.current.loading).toBe(false);
  });

  it("refetch() error from stale call does not overwrite fresh success", async () => {
    // Same failure mode, error path: an older fetch that rejects late
    // must not blank out the successful data from a newer fetch.
    const resolvers: Array<(v: string) => void> = [];
    const rejectors: Array<(e: Error) => void> = [];
    const fetcher = vi.fn(
      () =>
        new Promise<string>((resolve, reject) => {
          resolvers.push(resolve);
          rejectors.push(reject);
        }),
    );
    const { result } = renderHook(() => useApi(fetcher));

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    await act(async () => {
      resolvers[0]("initial");
    });

    act(() => {
      result.current.refetch();
      result.current.refetch();
    });
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(3));

    await act(async () => {
      resolvers[2]("fresh");
      rejectors[1](new Error("stale failure"));
    });

    expect(result.current.data).toBe("fresh");
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("late-resolving initial fetch does not overwrite refetch() result", async () => {
    // If the caller triggers refetch() while the mount fetch is still in
    // flight, the mount fetch's response must be discarded when it
    // eventually resolves.
    const resolvers: Array<(v: string) => void> = [];
    const fetcher = vi.fn(
      () => new Promise<string>((resolve) => resolvers.push(resolve)),
    );
    const { result } = renderHook(() => useApi(fetcher));

    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));

    // Refetch BEFORE the mount fetch resolves.
    act(() => {
      result.current.refetch();
    });
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));

    await act(async () => {
      resolvers[1]("refetch-result");
    });
    expect(result.current.data).toBe("refetch-result");

    // Now let the mount fetch finally resolve. Without the staleness
    // guard, this would clobber "refetch-result".
    await act(async () => {
      resolvers[0]("stale-mount-result");
    });

    expect(result.current.data).toBe("refetch-result");
  });
});
