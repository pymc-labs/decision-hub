import { useCallback } from "react";
import { useLocalStorage } from "./useLocalStorage";

const STORAGE_KEY = "dhub:recently-viewed";
const MAX_ITEMS = 5;

export interface RecentlyViewedSkill {
  org_slug: string;
  skill_name: string;
  description: string;
  safety_rating: string;
}

export function useRecentlyViewed() {
  const [items, setItems] = useLocalStorage<RecentlyViewedSkill[]>(STORAGE_KEY, []);

  const addRecentlyViewed = useCallback(
    (skill: RecentlyViewedSkill) => {
      setItems((prev) => {
        // Remove existing entry for same skill, prepend new one, cap at MAX_ITEMS
        const filtered = prev.filter(
          (s) => !(s.org_slug === skill.org_slug && s.skill_name === skill.skill_name)
        );
        return [skill, ...filtered].slice(0, MAX_ITEMS);
      });
    },
    [setItems]
  );

  const refresh = useCallback(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      setItems(raw ? (JSON.parse(raw) as RecentlyViewedSkill[]) : []);
    } catch {
      // ignore
    }
  }, [setItems]);

  return { items, addRecentlyViewed, refresh };
}
