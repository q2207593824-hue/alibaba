import { useCallback, useEffect, useRef, useState } from "react";

export type UseStaleRequestOptions<T> = {
  cacheKey?: string;
  staleMs?: number;
  initialData?: T | null;
  enabled?: boolean;
};

function readLs<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function writeLs(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // ignore
  }
}

export function useStaleRequest<T>(
  fetcher: () => Promise<T>,
  opts: UseStaleRequestOptions<T> = {},
) {
  const { cacheKey, staleMs = 30_000, initialData = null, enabled = true } = opts;
  const cached = cacheKey ? readLs<T>(cacheKey) : null;
  const [data, setData] = useState<T | null>(cached ?? initialData);
  const [loading, setLoading] = useState(enabled && !cached && !initialData);
  const [error, setError] = useState<string | null>(null);
  const lastOkAt = useRef(cached ? Date.now() - staleMs : 0);
  const inflight = useRef<Promise<void> | null>(null);

  const revalidate = useCallback(
    async (force = false) => {
      if (!enabled) return;
      const now = Date.now();
      if (!force && staleMs > 0 && now - lastOkAt.current < staleMs) return;

      if (inflight.current) {
        await inflight.current;
        return;
      }

      const hasData = data !== null && data !== undefined;
      if (!hasData) setLoading(true);

      inflight.current = (async () => {
        try {
          setError(null);
          const next = await fetcher();
          setData(next);
          lastOkAt.current = Date.now();
          if (cacheKey) writeLs(cacheKey, next);
        } catch (e: any) {
          setError(String(e?.message || e || "请求失败"));
        } finally {
          setLoading(false);
          inflight.current = null;
        }
      })();

      await inflight.current;
    },
    [cacheKey, data, enabled, fetcher, staleMs],
  );

  useEffect(() => {
    if (!enabled) return;
    void revalidate(false);
  }, [enabled, revalidate]);

  return { data, loading, error, revalidate, setData };
}
