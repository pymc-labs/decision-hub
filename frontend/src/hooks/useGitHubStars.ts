import { useState, useEffect } from "react";

const CACHE_KEY = "gh_stars_pymc-labs/decision-hub";
const CACHE_TTL_MS = 60 * 60 * 1000; // 1 hour

interface CacheEntry {
  stars: number;
  ts: number;
}

export function useGitHubStars(): number | null {
  const [stars, setStars] = useState<number | null>(() => {
    try {
      const raw = sessionStorage.getItem(CACHE_KEY);
      if (raw) {
        const entry: CacheEntry = JSON.parse(raw);
        if (Date.now() - entry.ts < CACHE_TTL_MS) return entry.stars;
      }
    } catch {
      // ignore corrupt cache
    }
    return null;
  });

  useEffect(() => {
    if (stars !== null) return;

    let cancelled = false;
    fetch("https://api.github.com/repos/pymc-labs/decision-hub", {
      headers: { Accept: "application/vnd.github.v3+json" },
    })
      .then((res) => {
        if (!res.ok) throw new Error(`GitHub API ${res.status}`);
        return res.json();
      })
      .then((data) => {
        if (cancelled) return;
        const count: number = data.stargazers_count;
        setStars(count);
        try {
          sessionStorage.setItem(CACHE_KEY, JSON.stringify({ stars: count, ts: Date.now() }));
        } catch {
          // storage full — not critical
        }
      })
      .catch(() => {
        // silently fail — button still works without the count
      });

    return () => {
      cancelled = true;
    };
  }, [stars]);

  return stars;
}
