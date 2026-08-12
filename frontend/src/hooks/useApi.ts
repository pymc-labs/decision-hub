import { useState, useEffect, useCallback, useRef } from "react";

interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[] = []): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Monotonically-increasing fetch id. Every in-flight request captures
  // the id it started with and is silently ignored on resolution when a
  // newer one has been issued. Guards against two independent races:
  //   1. Deps change while a fetch is in flight — old response would
  //      otherwise overwrite the new one.
  //   2. refetch() is called twice quickly (double-click on a retry
  //      button, or refetch() + subsequent deps change) — without this,
  //      whichever fetch resolves last wins, not the most recent one.
  const fetchIdRef = useRef(0);

  const refetch = useCallback(() => {
    const id = ++fetchIdRef.current;
    setLoading(true);
    setError(null);
    fetcher()
      .then((result) => {
        if (id !== fetchIdRef.current) return;
        setData(result);
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

  useEffect(() => {
    const id = ++fetchIdRef.current;
    setLoading(true);
    setError(null);
    fetcher()
      .then((result) => {
        if (id !== fetchIdRef.current) return;
        setData(result);
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

  return { data, loading, error, refetch };
}
