import { useEffect, useRef } from "react";
import { configApi, getMembershipToken, isDesktopClient } from "@/lib/api";

type AdminRuntimePayload = {
  revision?: number;
  data_analysis?: Record<string, any>;
  ai_image_gen?: Record<string, any>;
};

type Options = {
  enabled?: boolean;
  /** 正在编辑密钥时跳过同步，避免覆盖输入 */
  skipSync?: () => boolean;
  onDataAnalysisChange?: (data: Record<string, any>) => void;
  onAiImageGenChange?: (data: Record<string, any>) => void;
  onRevisionChange?: (revision: number) => void;
};

function unwrapRuntime(res: any): AdminRuntimePayload {
  const payload = res?.data ?? res;
  return (payload?.data ?? payload ?? {}) as AdminRuntimePayload;
}

/**
 * 跟本地 config revision 更新 UI（API Key / 模型）。
 * 桌面端云端 pull 由 App.tsx 统一处理，避免多页面重复轮询。
 */
export function useAdminRuntimeConfigSync(options: Options) {
  const {
    enabled = true,
    skipSync,
    onDataAnalysisChange,
    onAiImageGenChange,
    onRevisionChange,
  } = options;

  const lastRevisionRef = useRef<number | null>(null);
  const callbacksRef = useRef(options);
  callbacksRef.current = options;

  useEffect(() => {
    if (!enabled) return;
    if (!onDataAnalysisChange && !onAiImageGenChange) return;

    const refreshUiFromLocal = async () => {
      const runtimeRes = await configApi.getAdminRuntime();
      const runtime = unwrapRuntime(runtimeRes);
      if (runtime.data_analysis) {
        callbacksRef.current.onDataAnalysisChange?.(runtime.data_analysis);
      }
      if (runtime.ai_image_gen) {
        callbacksRef.current.onAiImageGenChange?.(runtime.ai_image_gen);
      }
    };

    const tick = async () => {
      if (skipSync?.()) return;
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      try {
        const revRes = await configApi.getRevision();
        const payload = revRes?.data ?? revRes;
        const data = payload?.data ?? payload ?? {};
        const revision = Number(data?.revision ?? 0);
        if (!revision) return;
        const prev = lastRevisionRef.current;
        if (prev === null) {
          lastRevisionRef.current = revision;
          await refreshUiFromLocal();
          callbacksRef.current.onRevisionChange?.(revision);
          return;
        }
        if (revision === prev) return;
        lastRevisionRef.current = revision;
        await refreshUiFromLocal();
        callbacksRef.current.onRevisionChange?.(revision);
      } catch {
        // ignore
      }
    };

    void tick();
    const timer = setInterval(tick, isDesktopClient() ? 30000 : 15000);
    return () => clearInterval(timer);
  }, [enabled, skipSync, onDataAnalysisChange, onAiImageGenChange]);
}

export function isMaskedSecret(v: string | undefined | null): boolean {
  const s = String(v || "").trim();
  if (!s || s === "***" || s.startsWith("***")) return true;
  if (s.length > 4 && s.slice(2, -2) && !s.slice(2, -2).replace(/\*/g, "")) return true;
  return false;
}

export function applyRuntimeApiKey(
  incomingKey: string | undefined,
  prevKey: string,
  setKey: (v: string) => void,
  setEditing: (v: string) => void
) {
  const next = String(incomingKey || "");
  if (!next || isMaskedSecret(next)) return;
  if (next === prevKey) return;
  setKey(next);
  setEditing(next);
}

/** @deprecated use applyRuntimeApiKey */
export const applyMaskedApiKey = applyRuntimeApiKey;
