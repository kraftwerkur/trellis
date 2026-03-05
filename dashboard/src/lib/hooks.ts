"use client";
import { useState, useEffect, useCallback, useRef } from "react";

/**
 * Stable polling hook — rock-solid, no flicker.
 * - Never clears data once loaded (even on error or re-mount)
 * - Loading only true until first successful fetch
 * - Deep JSON compare prevents unnecessary re-renders
 */
export function useStablePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number = 5000
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const lastJson = useRef<string>("");
  const mounted = useRef(true);
  const hasLoaded = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const result = await fetcher();
      if (!mounted.current) return;
      const json = JSON.stringify(result);
      if (json !== lastJson.current) {
        lastJson.current = json;
        setData(result);
      }
      setError(null);
      if (!hasLoaded.current) {
        hasLoaded.current = true;
        setLoading(false);
      }
    } catch (e) {
      if (!mounted.current) return;
      setError(e instanceof Error ? e.message : "Unknown error");
      // Still mark as loaded so we don't show skeleton forever
      if (!hasLoaded.current) {
        hasLoaded.current = true;
        setLoading(false);
      }
    }
  }, [fetcher]);

  useEffect(() => {
    mounted.current = true;
    refresh();
    if (intervalMs > 0) {
      const id = setInterval(refresh, intervalMs);
      return () => { mounted.current = false; clearInterval(id); };
    }
    return () => { mounted.current = false; };
  }, [refresh, intervalMs]);

  return { data, error, loading, refresh };
}

export const usePolling = useStablePolling;
