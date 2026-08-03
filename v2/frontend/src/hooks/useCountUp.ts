import { useEffect, useRef, useState } from 'react';

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Animate a number from 0 up to `target` on mount (and whenever `target`
 * changes), returning the current animated value. Purely presentational.
 * - Non-numeric / non-finite targets pass through unchanged.
 * - Under prefers-reduced-motion it snaps straight to the target (no animation).
 */
export function useCountUp(
  target: number | null | undefined,
  durationMs = 850,
): number | null | undefined {
  const [value, setValue] = useState<number | null | undefined>(() =>
    prefersReducedMotion() || typeof target !== 'number' || !Number.isFinite(target) ? target : 0,
  );
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (typeof target !== 'number' || !Number.isFinite(target) || prefersReducedMotion()) {
      setValue(target);
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3); // easeOutCubic
      setValue(target * eased);
      if (t < 1) rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [target, durationMs]);

  return value;
}
