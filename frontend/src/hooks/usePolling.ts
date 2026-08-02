import { useEffect, useRef, useState } from "react";

/**
 * Polls an async function at a fixed interval, keeping the latest result in state.
 *
 * Used by pages that show live-ish data (agent list, dashboard) so the operator
 * sees updates without hitting refresh. The first fetch runs immediately; every
 * `intervalMs` after that it fetches again while the component is mounted.
 *
 * A ref guards against setting state on an unmounted component (StrictMode
 * mounts a component twice in dev, which would otherwise cause a warning).
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
): { data: T | null; error: string | null; loading: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const mounted = useRef(true);

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    mounted.current = true;

    const load = async () => {
      try {
        const value = await fetcherRef.current();
        if (mounted.current) {
          setData(value);
          setError(null);
        }
      } catch (err) {
        if (mounted.current) {
          setError((err as Error).message);
        }
      } finally {
        if (mounted.current) {
          setLoading(false);
        }
      }
    };

    load();
    const timer = setInterval(load, intervalMs);

    return () => {
      mounted.current = false;
      clearInterval(timer);
    };
  }, [intervalMs]);

  return { data, error, loading };
}
