import { useState, useEffect, useRef, useCallback } from "react";

interface PaginatedResult<T> {
  items: T[];
  total: number;
  total_pages: number;
}

/**
 * Hook for infinite scrolling with server-side pagination.
 * Accumulates items across pages and uses IntersectionObserver
 * to trigger loading the next page when the sentinel element
 * scrolls into view.
 *
 * @param fetchPage - Function that fetches a specific page number
 * @param deps - Dependencies that trigger a full reset (e.g., filter values)
 */
export function useInfiniteScroll<T>(
  fetchPage: (page: number) => Promise<PaginatedResult<T>>,
  deps: unknown[],
) {
  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);

  const pageRef = useRef(1);
  const fetchIdRef = useRef(0);
  const loadingRef = useRef(false);
  const hasMoreRef = useRef(false);
  const errorRef = useRef(false);

  // Keep refs in sync with state for use in observer callback
  loadingRef.current = loading || loadingMore;
  hasMoreRef.current = hasMore;

  // Reset and fetch page 1 when deps change
  useEffect(() => {
    const id = ++fetchIdRef.current;
    pageRef.current = 1;
    setLoading(true);
    setLoadingMore(false);
    loadingRef.current = false;
    hasMoreRef.current = false;
    errorRef.current = false;
    setError(null);
    setHasMore(false);

    fetchPage(1)
      .then((result) => {
        if (id !== fetchIdRef.current) return;
        setItems(result.items);
        setTotal(result.total);
        setHasMore(1 < result.total_pages);
      })
      .catch((err) => {
        if (id !== fetchIdRef.current) return;
        setError(err.message);
      })
      .finally(() => {
        if (id !== fetchIdRef.current) return;
        setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  // Load next page — uses refs to avoid stale closures in the observer
  const loadNextPage = useCallback(() => {
    if (loadingRef.current || !hasMoreRef.current || errorRef.current) return;

    const nextPage = pageRef.current + 1;
    const currentFetchId = fetchIdRef.current;

    loadingRef.current = true;
    setLoadingMore(true);

    fetchPage(nextPage)
      .then((result) => {
        if (currentFetchId !== fetchIdRef.current) return;
        pageRef.current = nextPage;
        setItems((prev) => [...prev, ...result.items]);
        setTotal(result.total);
        setHasMore(nextPage < result.total_pages);
      })
      .catch((err) => {
        if (currentFetchId !== fetchIdRef.current) return;
        setError(err.message);
        errorRef.current = true;
      })
      .finally(() => {
        if (currentFetchId !== fetchIdRef.current) return;
        setLoadingMore(false);
        loadingRef.current = false;
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  // Stable ref for observer callback
  const loadNextPageRef = useRef(loadNextPage);
  loadNextPageRef.current = loadNextPage;

  // Allow pages to retry after a load-more error
  const retry = useCallback(() => {
    errorRef.current = false;
    setError(null);
    loadNextPageRef.current();
  }, []);

  // IntersectionObserver via callback ref — handles DOM insertion/removal
  const observerRef = useRef<IntersectionObserver | null>(null);

  const sentinelRef = useCallback((node: HTMLDivElement | null) => {
    if (observerRef.current) {
      observerRef.current.disconnect();
      observerRef.current = null;
    }

    if (node) {
      observerRef.current = new IntersectionObserver(
        (entries) => {
          if (entries[0].isIntersecting) {
            loadNextPageRef.current();
          }
        },
        { rootMargin: "200px" },
      );
      observerRef.current.observe(node);
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => observerRef.current?.disconnect();
  }, []);

  return { items, total, loading, loadingMore, error, hasMore, sentinelRef, retry };
}
