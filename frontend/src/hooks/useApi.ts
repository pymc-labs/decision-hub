import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api/client";

interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  /** Human-readable error message, or null. Safe to render directly. */
  error: string | null;
  /**
   * HTTP status from the failed request (0 for network errors / timeouts),
   * or null when there's no error. Callers can branch on this for 401/404
   * handling without regex-matching the error message.
   */
  errorStatus: number | null;
  refetch: () => void;
}

/**
 * Run *fetcher* on mount and whenever any of *deps* change. Exposes
 * loading / data / error / errorStatus and a manual *refetch* hook.
 *
 * Staleness: a single monotonically-increasing fetch id is shared by
 * both the dep-driven effect and the manual *refetch* path. Whenever a
 * new fetch starts, any older in-flight fetch is ignored — so rapid
 * dep changes or fast double-clicks of *refetch* never commit a stale
 * result.
 */
export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);

  // Shared staleness token. Every fetch increments this; callbacks only
  // commit state when their captured id is still the latest.
  const fetchIdRef = useRef(0);
  // Keep the latest fetcher in a ref so refetch() can pick it up without
  // forcing the caller to memoise — refetch's identity stays stable
  // across renders.
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const runFetch = useCallback(() => {
    const id = ++fetchIdRef.current;
    setLoading(true);
    setError(null);
    setErrorStatus(null);

    fetcherRef.current()
      .then((result) => {
        if (id !== fetchIdRef.current) return;
        setData(result);
      })
      .catch((err: unknown) => {
        if (id !== fetchIdRef.current) return;
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
        setErrorStatus(err instanceof ApiError ? err.status : null);
      })
      .finally(() => {
        if (id !== fetchIdRef.current) return;
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    runFetch();
    // Bumping fetchIdRef inside runFetch acts as the cleanup — no
    // separate cancellation callback is needed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, loading, error, errorStatus, refetch: runFetch };
}
