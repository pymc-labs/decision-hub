import { useState, useEffect, useCallback, useRef } from "react";

interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

/**
 * Generic fetcher hook with staleness guards on both auto-fetch and
 * manual refetch. The auto-fetch path is correlated by a monotonically
 * increasing fetch id so an older in-flight request cannot overwrite
 * newer data when the dependency array changes rapidly (e.g. user types
 * into a search box). Manual refetches share the same counter so a
 * refetch issued while an auto-fetch is in flight still wins — the most
 * recent issue always wins, not the most recent return.
 */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fetchIdRef = useRef(0);

  const run = useCallback(() => {
    const id = ++fetchIdRef.current;
    setLoading(true);
    setError(null);
    fetcher()
      .then((result) => {
        if (id === fetchIdRef.current) setData(result);
      })
      .catch((err: unknown) => {
        if (id !== fetchIdRef.current) return;
        const message = err instanceof Error ? err.message : "Request failed";
        setError(message);
      })
      .finally(() => {
        if (id === fetchIdRef.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    run();
    // Unmount / dep-change increments the fetch id so pending promises
    // become no-ops on resolve. We deliberately don't try to abort the
    // underlying fetch — most consumers pass closures that wrap several
    // API calls and an AbortController would need plumbing through every
    // request-builder. The staleness guard is enough to keep UI state
    // correct; if a route consistently cancels expensive requests, push
    // an AbortController in via that route's fetcher instead.
    return () => {
      // Invalidate any in-flight result that hasn't resolved yet.
      fetchIdRef.current += 1;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, loading, error, refetch: run };
}
