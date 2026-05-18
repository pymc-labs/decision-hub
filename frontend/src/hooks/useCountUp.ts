import { useState, useEffect, useRef } from "react";

/**
 * Animates a number from 0 to `target` over `duration` ms once the
 * referenced element scrolls into view. Uses requestAnimationFrame
 * with an ease-out curve for a smooth counting effect.
 */
export function useCountUp(target: number, duration = 1500): [number, React.RefObject<HTMLElement | null>] {
  const [value, setValue] = useState(0);
  const ref = useRef<HTMLElement | null>(null);
  const hasAnimated = useRef(false);
  const animatedFor = useRef<number | null>(null);
  const rafId = useRef<number | null>(null);

  useEffect(() => {
    // Don't set up the observer until we have a real value from the API.
    // This prevents hasAnimated from being locked to true while target is
    // still zero (before data loads), which would block the real animation.
    if (target === 0) return;

    // If `target` changes (e.g. stats refetch resolves to a different number),
    // clear the latch so the new value can be animated. Without this the
    // counter would stay frozen on the very first non-zero value it ever saw.
    if (animatedFor.current !== target) {
      hasAnimated.current = false;
    }

    const el = ref.current;
    if (!el || hasAnimated.current) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting || hasAnimated.current) return;
        hasAnimated.current = true;
        animatedFor.current = target;
        observer.disconnect();

        const start = performance.now();
        const step = (now: number) => {
          const elapsed = now - start;
          const progress = Math.min(elapsed / duration, 1);
          // ease-out cubic
          const eased = 1 - Math.pow(1 - progress, 3);
          setValue(Math.round(eased * target));

          if (progress < 1) {
            rafId.current = requestAnimationFrame(step);
          } else {
            rafId.current = null;
          }
        };
        rafId.current = requestAnimationFrame(step);
      },
      { threshold: 0.2 }
    );

    observer.observe(el);
    return () => {
      observer.disconnect();
      if (rafId.current !== null) {
        cancelAnimationFrame(rafId.current);
        rafId.current = null;
      }
    };
  }, [target, duration]);

  return [value, ref];
}
