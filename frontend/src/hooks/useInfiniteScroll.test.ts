import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useInfiniteScroll } from "./useInfiniteScroll";

interface Item {
  id: number;
}

interface Page {
  items: Item[];
  total: number;
  total_pages: number;
}

/**
 * Return a deferred promise plus a resolver so tests can control fetch
 * timing precisely. Used to observe the state *between* a dep change and
 * the new page-1 resolution — the exact window where the bug used to
 * leave stale items on screen.
 */
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("useInfiniteScroll", () => {
  it("clears items when deps change so pages show the spinner instead of stale cards", async () => {
    const page1Deferred = deferred<Page>();
    const page2Deferred = deferred<Page>();

    const fetchPage = vi
      .fn<(page: number) => Promise<Page>>()
      .mockReturnValueOnce(page1Deferred.promise)
      .mockReturnValueOnce(page2Deferred.promise);

    // Deps as a top-level ref so we can flip them between renders.
    let deps: unknown[] = ["category:a"];
    const { result, rerender } = renderHook(() => useInfiniteScroll<Item>(fetchPage, deps));

    // Complete the first load.
    await act(async () => {
      page1Deferred.resolve({ items: [{ id: 1 }, { id: 2 }], total: 2, total_pages: 1 });
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toHaveLength(2);
    expect(result.current.total).toBe(2);

    // Flip deps — the hook should IMMEDIATELY clear items and total so a
    // page rendering "spinner if items.length === 0" shows the spinner,
    // not the previous filter's cards under new filter labels.
    deps = ["category:b"];
    act(() => {
      rerender();
    });

    expect(result.current.loading).toBe(true);
    expect(result.current.items).toEqual([]);
    expect(result.current.total).toBe(0);

    // New page-1 arrives with different data.
    await act(async () => {
      page2Deferred.resolve({ items: [{ id: 99 }], total: 1, total_pages: 1 });
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toEqual([{ id: 99 }]);
    expect(result.current.total).toBe(1);
    expect(fetchPage).toHaveBeenCalledTimes(2);
  });
});
