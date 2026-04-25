import { useEffect, useState } from "react";

export function formatMMSS(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

/**
 * Returns elapsed seconds since the server-provided ISO timestamp.
 * Tick is purely a render trigger; the elapsed value is always derived
 * from `Date.now() - new Date(iso)` so we never trust the client clock
 * for the origin of the timer.
 */
export function useElapsedSeconds(isoStartedAt?: string | null): number {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!isoStartedAt) return;
    const id = window.setInterval(() => setTick((t) => (t + 1) % 1_000_000), 1000);
    return () => window.clearInterval(id);
  }, [isoStartedAt]);

  if (!isoStartedAt) return 0;
  const started = Date.parse(isoStartedAt);
  if (Number.isNaN(started)) return 0;
  return Math.max(0, Math.floor((Date.now() - started) / 1000));
}

/** Countdown remaining (seconds) from an ISO start + duration. */
export function useRemainingSeconds(
  isoStartedAt?: string | null,
  totalSeconds: number = 60,
): number {
  const elapsed = useElapsedSeconds(isoStartedAt);
  return Math.max(0, totalSeconds - elapsed);
}
