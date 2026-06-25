import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { configApi, subscribeConfigUpdates } from "@/lib/api";

type ConfigRoot = Record<string, unknown> | null;

type ConfigContextValue = {
  config: ConfigRoot;
  ready: boolean;
  revalidate: (force?: boolean) => Promise<void>;
};

const ConfigContext = createContext<ConfigContextValue | null>(null);

function unwrapConfigPayload(raw: unknown): ConfigRoot {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  if ("data" in o && o.data && typeof o.data === "object") {
    return o.data as Record<string, unknown>;
  }
  return o;
}

export function ConfigProvider({ children }: { children: ReactNode }) {
  const cached = configApi.getCached();
  const [config, setConfig] = useState<ConfigRoot>(() => unwrapConfigPayload(cached));
  const [ready, setReady] = useState(!!config);

  const applyRaw = useCallback((raw: unknown) => {
    const next = unwrapConfigPayload(raw);
    if (next) {
      setConfig(next);
      setReady(true);
    }
  }, []);

  const revalidate = useCallback(async (force = false) => {
    try {
      const raw = await configApi.get(force);
      applyRaw(raw);
    } catch {
      const stale = configApi.getCached();
      if (stale) applyRaw(stale);
    }
  }, [applyRaw]);

  useEffect(() => {
    if (!config) {
      void configApi.prime(false).then(applyRaw).catch(() => undefined);
    } else {
      void configApi.revalidateInBackground();
    }
    return subscribeConfigUpdates(() => {
      applyRaw(configApi.getCached());
    });
  }, [applyRaw, config]);

  const value = useMemo(
    () => ({ config, ready, revalidate }),
    [config, ready, revalidate],
  );

  return <ConfigContext.Provider value={value}>{children}</ConfigContext.Provider>;
}

export function useConfigContext() {
  const ctx = useContext(ConfigContext);
  if (!ctx) {
    throw new Error("useConfigContext must be used within ConfigProvider");
  }
  return ctx;
}

/** Safe accessor when provider optional (legacy paths). Falls back to sync cache. */
export function useConfigSection<T = Record<string, unknown>>(section: string): {
  section: T | null;
  ready: boolean;
  revalidate: (force?: boolean) => Promise<void>;
} {
  const ctx = useContext(ConfigContext);
  const cached = unwrapConfigPayload(configApi.getCached());
  const sec = ctx?.config?.[section] ?? cached?.[section];

  useEffect(() => {
    if (sec) return;
    void configApi.getSection(section).catch(() => undefined);
  }, [section, sec]);

  return {
    section: (sec as T) ?? null,
    ready: ctx?.ready ?? !!cached?.[section],
    revalidate: ctx?.revalidate ?? (async (force?: boolean) => {
      await configApi.getSection(section, !!force);
    }),
  };
}

export function getConfigSectionSync(section: string): Record<string, unknown> | null {
  const root = unwrapConfigPayload(configApi.getCached());
  const sec = root?.[section];
  return sec && typeof sec === "object" ? (sec as Record<string, unknown>) : null;
}
