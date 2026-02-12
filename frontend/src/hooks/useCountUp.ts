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

  useEffect(() => {
    // Don't set up the observer until we have a real value from the API.
    // This prevents hasAnimated from being locked to true while target is
    // still zero (before data loads), which would block the real animation.
    if (target === 0) return;

    const el = ref.current;
    if (!el || hasAnimated.current) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting || hasAnimated.current) return;
        hasAnimated.current = true;
        observer.disconnect();

        const start = performance.now();
        const step = (now: number) => {
          const elapsed = now - start;
          const progress = Math.min(elapsed / duration, 1);
          // ease-out cubic
          const eased = 1 - Math.pow(1 - progress, 3);
          setValue(Math.round(eased * target));

          if (progress < 1) {
            requestAnimationFrame(step);
          }
        };
        requestAnimationFrame(step);
      },
      { threshold: 0.2 }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [target, duration]);

  return [value, ref];
}
