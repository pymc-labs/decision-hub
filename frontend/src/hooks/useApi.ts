import { useState, useEffect, useCallback, useRef } from "react";

interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

/**
 * Fetch data with a monotonically-increasing fetch id so a slow response
 * can't overwrite a fresher one. Both the deps-driven effect and the
 * user-triggered `refetch` bump the same id; only the highest id in
 * flight is allowed to write to state.
 *
 * The previous implementation guarded the deps effect only, so a slow
 * `refetch()` could land after new deps had already produced fresh data
 * and silently roll it back to the stale value.
 */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const fetchIdRef = useRef(0);

  const runFetch = useCallback(() => {
    fetchIdRef.current += 1;
    const myId = fetchIdRef.current;
    setLoading(true);
    setError(null);
    fetcher()
      .then((result) => {
        if (fetchIdRef.current === myId) setData(result);
      })
      .catch((err) => {
        if (fetchIdRef.current === myId) setError(err.message);
      })
      .finally(() => {
        if (fetchIdRef.current === myId) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  const refetch = useCallback(() => {
    runFetch();
  }, [runFetch]);

  useEffect(() => {
    runFetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, loading, error, refetch };
}
