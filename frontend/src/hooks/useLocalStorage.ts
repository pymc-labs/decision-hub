import { useState, useCallback } from "react";

export function useLocalStorage<T>(
  key: string,
  initial: T
): [T, (val: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw ? (JSON.parse(raw) as T) : initial;
    } catch (err) {
      // Surface corrupted/unreadable storage so we don't silently drop user state.
      console.warn(`useLocalStorage: failed to parse "${key}", falling back to initial value`, err);
      return initial;
    }
  });

  const set = useCallback(
    (val: T | ((prev: T) => T)) => {
      setValue((prev) => {
        const next = typeof val === "function" ? (val as (p: T) => T)(prev) : val;
        try {
          localStorage.setItem(key, JSON.stringify(next));
        } catch (err) {
          // Most often quota exceeded; warn so the issue is debuggable in DevTools.
          console.warn(`useLocalStorage: failed to write "${key}"`, err);
        }
        return next;
      });
    },
    [key]
  );

  return [value, set];
}
