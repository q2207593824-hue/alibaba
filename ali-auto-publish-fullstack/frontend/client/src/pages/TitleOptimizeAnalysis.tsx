import { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ChevronRight, Wand2 } from "lucide-react";
import { analysisApi, configApi, ensureRuntimeSecretsForAiTask, getMembershipToken, isDesktopClient } from "@/lib/api";
import { applyRuntimeApiKey, isMaskedSecret, useAdminRuntimeConfigSync } from "@/hooks/useAdminRuntimeConfigSync";
import { toast } from "sonner";

type OptimizeRow = {
  product_id: string;
  original_title: string;
  suggested_title: string;
  source: string;
  optimize_time?: string;
  optimize_attr?: string;
  history_data?: string;
  detail_file?: string;
  error?: string;
};

const TITLE_OPTIMIZE_RESULTS_CACHE_KEY = "title_optimize_results_cache_v1";

const ANOMALY_COL_LABELS: Record<string, string> = {
  productId: "产品ID",
  shopExposure: "全店曝光",
  p4pExposure: "全站推曝光",
  searchExposure: "搜索曝光",
  naturalExposure: "自然曝光",
  sceneExposure: "场景曝光",
  shopClicks: "全店点击",
  p4pClicks: "全站推点击",
  searchClicks: "搜索点击",
  naturalClicks: "自然点击",
  sceneClicks: "场景点击",
};

function readResultsCache(): { generated_at?: string; results: OptimizeRow[] } | null {
  try {
    const raw = localStorage.getItem(TITLE_OPTIMIZE_RESULTS_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || !Array.isArray(parsed.results)) return null;
    return {
      generated_at: String(parsed.generated_at || ""),
      results: parsed.results,
    };
  } catch {
    return null;
  }
}

function writeResultsCache(value: { generated_at?: string; results: OptimizeRow[] }) {
  try {
    localStorage.setItem(TITLE_OPTIMIZE_RESULTS_CACHE_KEY, JSON.stringify(value));
  } catch {
    // ignore
  }
}

export default function TitleOptimizeAnalysis() {
  const [manualIds, setManualIds] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [runMessage, setRunMessage] = useState("");
  const [runError, setRunError] = useState("");
  const [pointsEstimate, setPointsEstimate] = useState<Record<string, any> | null>(null);
  const [pointsPerItem, setPointsPerItem] = useState(0.2);

  const [apiKey, setApiKey] = useState("");
  const [apiKeyEditing, setApiKeyEditing] = useState("");
  const [isApiKeyEditing, setIsApiKeyEditing] = useState(false);
  const [modelName, setModelName] = useState("doubao-seed-2-0-pro-260215");
  const [resultFile, setResultFile] = useState("");
  const [detailDir, setDetailDir] = useState("");

  const [results, setResults] = useState<{ generated_at?: string; results: OptimizeRow[] }>(() => {
    const cached = readResultsCache();
    return cached || { results: [] };
  });

  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogTitle, setDialogTitle] = useState("");
  const [dialogContent, setDialogContent] = useState("");

  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [pickerSource, setPickerSource] = useState<"anomaly" | "new" | "all">("all");
  const [pickerSheet, setPickerSheet] = useState("全店曝光次数");
  const [pickerCols, setPickerCols] = useState<string[]>([]);
  const [pickerRows, setPickerRows] = useState<any[]>([]);
  const [pickerSelectedIds, setPickerSelectedIds] = useState<string[]>([]);
  const [pickerSortKey, setPickerSortKey] = useState<string>("产品ID");
  const [pickerSortDir, setPickerSortDir] = useState<"asc" | "desc">("asc");
  const [pickerDataVersion, setPickerDataVersion] = useState<string>("");
  const [versionToastShown, setVersionToastShown] = useState(false);
  const pollRef = useRef<number | null>(null);
  const resultsPollRef = useRef<number | null>(null);

  const isAdminSession = useMemo(() => {
    try {
      return (localStorage.getItem("admin_console_logged_in") || "") === "1";
    } catch {
      return false;
    }
  }, []);

  const loadConfig = async () => {
    try {
      const da = (await configApi.getSection("data_analysis")) || {};
      const rawKey = String(da.doubao_api_key || "");
      setApiKey(rawKey);
      setApiKeyEditing(rawKey);
      setIsApiKeyEditing(false);
      setModelName(da.doubao_model_name || "doubao-seed-2-0-pro-260215");
      setResultFile(da.title_optimize_result_file || "");
      setDetailDir(da.title_optimize_detail_dir || "");
    } catch {
      // ignore
    }
  };

  const apiKeyRef = useRef(apiKey);
  apiKeyRef.current = apiKey;

  useAdminRuntimeConfigSync({
    enabled: isDesktopClient() && !!getMembershipToken(),
    skipSync: () => isApiKeyEditing,
    onDataAnalysisChange: (da) => {
      if (da.doubao_model_name) {
        setModelName(String(da.doubao_model_name));
      }
      applyRuntimeApiKey(
        da.doubao_api_key,
        apiKeyRef.current,
        setApiKey,
        setApiKeyEditing
      );
    },
  });

  const saveConfig = async () => {
    try {
      const finalKey = isApiKeyEditing ? String(apiKeyEditing || "").trim() : String(apiKey || "").trim();
      const current = (await configApi.getSection("data_analysis")) || {};
      const adminFields: Record<string, string> = {};
      if (isAdminSession) {
        if (modelName) adminFields.doubao_model_name = modelName;
        if (finalKey && !isMaskedSecret(finalKey)) {
          adminFields.doubao_api_key = finalKey;
        }
      }
      await configApi.updateSection("data_analysis", {
        ...current,
        ...adminFields,
        title_optimize_result_file: resultFile,
        title_optimize_detail_dir: detailDir,
      });
      configApi.invalidateCache();
      setApiKey(finalKey);
      setApiKeyEditing(finalKey);
      setIsApiKeyEditing(false);
      toast.success("产品优化建议配置已保存");
    } catch (e: any) {
      toast.error(e?.message || "保存配置失败");
    }
  };

  const refreshStatus = async () => {
    try {
      const res = await analysisApi.getStatus("title_optimize");
      const payload = res?.data || res;
      const status = payload?.data || payload;
      const nextStatus = String(status?.status || "idle");
      const errText = String(status?.error || "");
      const staleKeyError = nextStatus === "failed" && /API Key|脱敏占位|api key/i.test(errText);

      setIsRunning(nextStatus === "running" || nextStatus === "stopping");
      setRunMessage(
        nextStatus === "running"
          ? `当前状态：运行中${status?.current_step ? `｜${status.current_step}` : ""}`
          : nextStatus === "stopping"
            ? "当前状态：正在停止"
            : nextStatus === "completed"
              ? `当前状态：已完成${status?.current_step ? `｜${status.current_step}` : ""}`
              : staleKeyError
                ? "当前状态：上次分析失败（配置问题）。管理员更新后请重新点击「开始分析」"
                : nextStatus === "failed"
                  ? `当前状态：已失败${errText ? `｜${errText}` : ""}`
                  : "当前状态：空闲"
      );
      setRunError(staleKeyError ? "" : nextStatus === "failed" ? errText || "任务执行失败" : "");
    } catch (e: any) {
      setRunMessage("");
      setRunError(e?.message || "获取状态失败");
    }
  };

  const normalizeResultsPayload = (payload: any) => {
    const raw = payload?.data ?? payload;
    const data = raw?.data && !Array.isArray(raw?.data) ? raw.data : raw;
    const candidates = [
      raw?.results,
      data?.results,
      raw?.data?.results,
      data?.data?.results,
      raw?.rows,
      data?.rows,
      raw?.data?.rows,
      data?.data?.rows,
    ];
    const nextResults = candidates.find((x) => Array.isArray(x)) || [];
    return {
      generated_at: raw?.generated_at || data?.generated_at || raw?.data?.generated_at || data?.data?.generated_at || "",
      source_file: raw?.source_file || data?.source_file || raw?.data?.source_file || data?.data?.source_file || "",
      result_count: Number(raw?.result_count || data?.result_count || raw?.data?.result_count || data?.data?.result_count || nextResults.length || 0),
      results: nextResults,
    };
  };


  const refreshResults = async () => {
    try {
      const res = await analysisApi.getTitleOptimizeResults();
      const next = normalizeResultsPayload(res);
      setResults((prev) => {
        const keptResults = next.results.length > 0 ? next.results : prev.results;
        const nextState = {
          generated_at: next.generated_at || prev.generated_at,
          results: keptResults,
        };
        if (keptResults.length > 0) {
          writeResultsCache(nextState);
        }
        return nextState;
      });
      if (next.results.length > 0) {
        stopResultsPoll();
      }
      return next.results;
    } catch (e) {
      console.warn("刷新产品优化建议结果失败，保留当前展示数据", e);
      return [];
    }
  };

  const stopPoll = () => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const stopResultsPoll = () => {
    if (resultsPollRef.current !== null) {
      window.clearInterval(resultsPollRef.current);
      resultsPollRef.current = null;
    }
  };

  const refreshPointsPricing = async () => {
    try {
      const res: any = await analysisApi.getPointsPricing();
      const payload = res?.data ?? res;
      const data = payload?.data ?? payload ?? {};
      const v = Number(data?.title_optimize_per_item);
      if (Number.isFinite(v) && v >= 0) setPointsPerItem(v);
    } catch {
      // keep default
    }
  };

  const parsePointsApiError = (e: any): string => {
    const status = Number(e?.response?.status || 0);
    const detail = e?.response?.data?.detail;
    const msg =
      typeof detail === "string"
        ? detail
        : typeof detail === "object" && detail
          ? String(detail.message || detail.msg || "")
          : String(e?.message || "");
    if (status === 503 || /云端积分/.test(msg)) {
      return msg || "云端积分服务暂不可用，请稍后重试";
    }
    if (status === 401 || /重新登录会员账号|登录会话在云端失效|本地登录会话/.test(msg)) {
      return msg || "登录会话已失效，请退出后重新登录会员账号";
    }
    return msg;
  };

  const refreshPointsEstimate = async (sourceFile?: string) => {
    if (isAdminSession) {
      setPointsEstimate({ skip_points: true });
      return;
    }
    try {
      const res: any = await analysisApi.getTitleOptimizePointsEstimate(sourceFile ?? manualIds.trim());
      const payload = res?.data ?? res;
      const est = payload?.data ?? payload ?? null;
      setPointsEstimate(est);
      const per = Number(est?.per_item_cost);
      if (Number.isFinite(per) && per >= 0) setPointsPerItem(per);
    } catch (e: any) {
      const cloudMsg = parsePointsApiError(e);
      if (/云端积分/.test(cloudMsg)) {
        setPointsEstimate({ cloud_unavailable: true, points_error: cloudMsg });
      } else if (/重新登录|本地登录会话|登录会话/.test(cloudMsg)) {
        setPointsEstimate({ cloud_unavailable: true, points_error: cloudMsg });
      } else {
        setPointsEstimate(null);
      }
    }
  };

  const startAnalyze = async () => {
    try {
      stopPoll();
      setRunError("");
      setRunMessage("开始检查产品输入...");

      const inspectRes = await analysisApi.inspectTitleOptimizeInputs({ task_type: "title_optimize", source_file: manualIds.trim() });
      const inspectPayload = inspectRes?.data || inspectRes;
      const inspectData = inspectPayload?.data || inspectPayload;
      const rows = Array.isArray(inspectData?.rows) ? inspectData.rows : [];
      const missing = rows.filter((r: any) => !r?.has_title || !r?.has_image);

      if (missing.length > 0) {
        const summary = missing.slice(0, 5).map((r: any) => {
          const parts = [];
          if (!r?.has_title) parts.push("标题缺失");
          if (!r?.has_image) parts.push("图片缺失");
          const kwCount = Number(r?.keyword_count || 0);
          if (kwCount === 0) parts.push("无关键词");
          return `${r?.product_id || "未知ID"}(${parts.join("/" )})`;
        }).join("，");
        const msg = `开始前检查未通过：${summary}${missing.length > 5 ? ` 等共 ${missing.length} 个产品` : ""}`;
        setRunError(msg);
        setRunMessage("当前状态：未启动，先补齐产品资料");
        toast.error(msg);
        return;
      }

      setRunMessage(`输入检查通过，准备启动${rows.length ? `｜共 ${rows.length} 个产品` : ""}`);

      if (!isAdminSession) {
        let estimate: Record<string, any> | null = null;
        try {
          const estRes: any = await analysisApi.getTitleOptimizePointsEstimate(manualIds.trim());
          const estPayload = estRes?.data ?? estRes;
          estimate = estPayload?.data ?? estPayload ?? null;
          setPointsEstimate(estimate);
        } catch (e: any) {
          const cloudMsg = parsePointsApiError(e);
          if (/云端积分/.test(cloudMsg)) {
            setRunError(cloudMsg);
            setRunMessage("当前状态：未启动，云端积分服务异常");
            toast.error(cloudMsg);
            return;
          }
          estimate = null;
        }
        if (estimate?.cloud_unavailable) {
          const cloudMsg = String(estimate.points_error || "云端积分服务暂不可用，请稍后重试");
          setRunError(cloudMsg);
          setRunMessage("当前状态：未启动，云端积分服务异常");
          toast.error(cloudMsg);
          return;
        }
        if (estimate && estimate.skip_points !== true && estimate.sufficient === false) {
          const msg = `积分不足：余额 ${estimate.balance ?? 0}，预计至少需 ${estimate.estimated_total_cost ?? estimate.whole_points_required ?? 0} 积分`;
          setRunError(msg);
          setRunMessage("当前状态：未启动，积分不足");
          toast.error(msg);
          return;
        }
      }

      await ensureRuntimeSecretsForAiTask();
      const startRes = await analysisApi.start({ task_type: "title_optimize", source_file: manualIds.trim() });
      const payload = startRes?.data || startRes;
      const task = payload?.task || payload?.data?.task || {};
      const initialStatus = String(task?.status || "");
      if (initialStatus && !["running", "stopping", "idle"].includes(initialStatus)) {
        throw new Error(payload?.message || "任务未成功启动");
      }

      toast.success(payload?.message || "产品优化建议分析已启动");
      setIsRunning(true);
      setRunError("");
      setRunMessage(payload?.message || "产品优化建议分析已启动");
      await refreshResults();

      let sawRunning = initialStatus === "running";
      pollRef.current = window.setInterval(async () => {
        try {
          const res = await analysisApi.getStatus("title_optimize");
          const statusPayload = res?.data || res;
          const status = statusPayload?.data || statusPayload;
          const s = String(status?.status || "");

          if (s === "running") {
            sawRunning = true;
            setIsRunning(true);
            return;
          }

          if (sawRunning && (s === "completed" || s === "failed" || s === "idle")) {
            stopPoll();
            await refreshResults();
            setManualIds("");
            setPickerSelectedIds([]);
            refreshStatus();
          }
        } catch {
          // ignore
        }
      }, 1500);

      await refreshStatus();
    } catch (e: any) {
      setIsRunning(false);
      stopPoll();
      setRunMessage("当前状态：启动失败");
      setRunError(e?.message || "启动失败");
      toast.error(e?.message || "启动失败");
    }
  };

  const stopAnalyze = async () => {
    try {
      stopPoll();
      await analysisApi.stop("title_optimize");
      toast.info("已请求停止分析");
      setRunMessage("当前状态：已请求停止");
      await refreshStatus();
    } catch (e: any) {
      toast.error(e?.message || "停止失败");
    }
  };

  const openDetail = async (row: OptimizeRow) => {
    try {
      const res = await analysisApi.getTitleOptimizeDetail(row.product_id);
      const payload = res?.data || res;
      const data = payload?.data || payload;
      setDialogTitle(`产品 ${row.product_id} 详细分析`);
      setDialogContent(String(data?.content || "暂无详情"));
      setDialogOpen(true);
    } catch (e: any) {
      toast.error(e?.message || "读取详情失败");
    }
  };

  const normalizePid = (v: any) => {
    const s = String(v ?? "").replace(/\.0+$/, "").trim();
    if (!s) return "";
    const byParam = s.match(/(?:itemId=|productId=|id=)(\d{10,20})/i);
    if (byParam) return byParam[1];
    const arr = s.match(/\d{10,20}/g);
    if (arr && arr.length) return arr.sort((a, b) => b.length - a.length)[0];
    return s;
  };

  const loadPickerData = async (source = pickerSource) => {
    setPickerLoading(true);
    try {
      const da = (await configApi.getSection("data_analysis")) || {};
      const outputFile = da.output_file || undefined;
      const newOutputFile = da.new_output_file || undefined;
      const volatilityPath = da.volatility_file_path || undefined;

      let colsRaw: string[] = [];
      let rows: any[] = [];
      let dataVersion = "";

      if (source === "anomaly") {
        const res = await analysisApi.getVolatilityAnomaly(volatilityPath || undefined);
        const payload = res?.data || res;
        const data = payload?.data || payload;
        colsRaw = ["productId", "shopExposure", "p4pExposure", "searchExposure", "naturalExposure", "sceneExposure", "shopClicks", "p4pClicks", "searchClicks", "naturalClicks", "sceneClicks"];
        rows = Array.isArray(data?.rows) ? data.rows : [];
        dataVersion = `anomaly|${String(volatilityPath || "")}`;
      } else if (source === "new") {
        const res = await analysisApi.getNewLinksMonitor(newOutputFile || undefined, "全店曝光次数");
        const payload = res?.data || res;
        const data = payload?.data || payload;
        colsRaw = Array.isArray(data?.columns) ? (data.columns as any[]).map((x) => String(x ?? "")) : [];
        rows = Array.isArray(data?.rows) ? data.rows : [];
        dataVersion = `${String(data?.file || newOutputFile || "")}|${String(data?.file_mtime || "")}|new`;
      } else {
        const res = await analysisApi.getStatisticsTable(outputFile, pickerSheet);
        const payload = res?.data || res;
        const data = payload?.data || payload;
        colsRaw = Array.isArray(data?.columns)
          ? (data.columns as any[]).map((x) => String(x ?? ""))
          : [];
        rows = Array.isArray(data?.rows) ? data.rows : [];
        dataVersion = `${String(data?.file || "")}|${String(data?.file_mtime || "")}|${String(pickerSheet || "")}`;
      }

      setPickerDataVersion(dataVersion);

      const isWeekCol = (c: string) => /^\d{6}-\d{6}$/.test(String(c));
      const weekCols = colsRaw.filter((c: string) => isWeekCol(c)).sort((a: string, b: string) => String(b).localeCompare(String(a)));
      const nonWeekCols = colsRaw.filter((c: string) => !isWeekCol(c));
      const cols = source === "anomaly"
        ? ["productId", ...nonWeekCols.filter((c) => c !== "productId")]
        : [
            ...(nonWeekCols.includes("产品ID") ? ["产品ID"] : []),
            ...nonWeekCols.filter((c) => c !== "产品ID"),
            ...weekCols,
          ];

      setPickerCols(cols);
      setPickerRows(rows);

      if (source === "anomaly") {
        setPickerSortKey("shopExposure");
        setPickerSortDir("asc");
      } else if (weekCols.length > 0) {
        setPickerSortKey(weekCols[0]);
        setPickerSortDir("desc");
      } else if (cols.includes("产品ID")) {
        setPickerSortKey("产品ID");
        setPickerSortDir("asc");
      }
    } catch (e: any) {
      toast.error(e?.message || "读取产品数据失败");
      setPickerCols([]);
      setPickerRows([]);
    } finally {
      setPickerLoading(false);
    }
  };

  const togglePick = (pidRaw: any) => {
    const pid = normalizePid(pidRaw);
    if (!pid) return;
    setPickerSelectedIds((prev) => (prev.includes(pid) ? prev.filter((x) => x !== pid) : [...prev, pid]));
  };

  const confirmPick = () => {
    const text = pickerSelectedIds.join(",");
    setManualIds(text);
    setPickerOpen(false);
  };

  useEffect(() => {
    const boot = async () => {
      await loadConfig();
      await refreshResults();
      await refreshPointsPricing();
      await refreshPointsEstimate();
      await refreshStatus();
    };
    void boot();
  }, []);

  useEffect(() => {
    if (!isRunning) return;
    const t = window.setInterval(refreshStatus, 4000);
    resultsPollRef.current = window.setInterval(() => {
      refreshResults();
    }, 6000);
    return () => {
      window.clearInterval(t);
      stopResultsPoll();
    };
  }, [isRunning]);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== TITLE_OPTIMIZE_RESULTS_CACHE_KEY) return;
      const cached = readResultsCache();
      if (cached) setResults(cached);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  useEffect(() => {
    if (!pickerOpen) return;
    try {
      const params = new URLSearchParams(window.location.search || "");
      const source = (params.get("source") || "").trim();
      const ids = (params.get("ids") || "").trim();
      if (source === "anomaly" || source === "new" || source === "all") {
        setPickerSource(source);
      }
      if (ids) {
        const parsedIds = ids.split(",").map((x) => normalizePid(x)).filter(Boolean);
        if (parsedIds.length) setPickerSelectedIds(parsedIds);
      }
    } catch {
      // ignore
    }
    loadPickerData(pickerSource);
  }, [pickerOpen, pickerSource, pickerSheet]);

  const allRows = useMemo(() => results.results || [], [results.results]);
  const hasResults = allRows.length > 0;

  const resultDataVersion = useMemo(() => {
    const rows = results.results || [];
    const first: any = rows.length > 0 ? rows[0] : null;
    const rowVersion = String(first?.data_version || "").trim();
    if (rowVersion) return rowVersion;
    // 兼容历史结果（无 data_version）：默认视为当前版本，保留已分析红色
    return pickerDataVersion;
  }, [results.results, pickerDataVersion]);

  useEffect(() => {
    // 仅在“产品优化建议”页面提示，且只提示一次；未登录/未绑定场景不会进到本页逻辑
    if (versionToastShown) return;
    if (!pickerDataVersion || !resultDataVersion) return;
    if (pickerDataVersion !== resultDataVersion) {
      toast.warning("检测到产品数据已更新，历史‘已分析(红色)’状态已失效，请重新分析。", { duration: 4000 });
      setVersionToastShown(true);
    }
  }, [pickerDataVersion, resultDataVersion, versionToastShown]);

  const pickerSortMark = (c: string) => (pickerSortKey === c ? (pickerSortDir === "asc" ? "↑" : "↓") : "");
  const onPickerSort = (c: string) => {
    if (pickerSortKey === c) {
      setPickerSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setPickerSortKey(c);
      setPickerSortDir(c === "产品ID" ? "asc" : "desc");
    }
  };

  const pickerDisplayRows = useMemo(() => {
    const rows = [...(pickerRows || [])];
    const key = pickerSortKey;
    if (!key) return rows;

    const isWeekCol = /^\d{6}-\d{6}$/.test(String(key));
    const baseCompare = (a: any, b: any) => {
      const avRaw = a?.[key];
      const bvRaw = b?.[key];

      if (key === "产品ID") {
        const as = normalizePid(avRaw);
        const bs = normalizePid(bvRaw);
        return pickerSortDir === "asc" ? as.localeCompare(bs) : bs.localeCompare(as);
      }

      if (isWeekCol) {
        const av = Number(String(avRaw ?? "0").replace(/,/g, ""));
        const bv = Number(String(bvRaw ?? "0").replace(/,/g, ""));
        const an = Number.isFinite(av) ? av : 0;
        const bn = Number.isFinite(bv) ? bv : 0;
        return pickerSortDir === "asc" ? an - bn : bn - an;
      }

      const av = Number(String(avRaw ?? "").replace(/,/g, ""));
      const bv = Number(String(bvRaw ?? "").replace(/,/g, ""));
      if (Number.isFinite(av) && Number.isFinite(bv) && String(avRaw ?? "").trim() !== "" && String(bvRaw ?? "").trim() !== "") {
        return pickerSortDir === "asc" ? av - bv : bv - av;
      }

      const as = String(avRaw ?? "");
      const bs = String(bvRaw ?? "");
      return pickerSortDir === "asc" ? as.localeCompare(bs) : bs.localeCompare(as);
    };

    rows.sort((a: any, b: any) => {
      // 产品异动：始终保持“全店曝光为负数”的行排在最前面
      if (pickerSource === "anomaly") {
        const aNeg = Number(String(a?.shopExposure ?? 0).replace(/,/g, "")) < 0;
        const bNeg = Number(String(b?.shopExposure ?? 0).replace(/,/g, "")) < 0;
        if (aNeg !== bNeg) return aNeg ? -1 : 1;
      }
      return baseCompare(a, b);
    });

    return rows;
  }, [pickerRows, pickerSortKey, pickerSortDir, pickerSource]);

  const formatTitleVersions = (text: string) => {
    const raw = String(text || "").trim();
    if (!raw) return "";
    const lines = raw
      .split(/\r?\n/)
      .map((x) => x.trim())
      .filter(Boolean)
      .map((x) => x.replace(/^[\-•\d\.、\s]+/, "").trim());

    const v1 = lines[0] || raw;
    const v2 = lines[1] || "";
    return v2 ? `版本1：${v1}\n版本2：${v2}` : `版本1：${v1}`;
  };

  const renderMarkdownLike = (content: string) => {
    const lines = String(content || "").split(/\r?\n/);
    return (
      <article className="max-w-none text-sm leading-7 text-foreground">
        {lines.map((line, idx) => {
          const t = line.trim();
          if (!t) return <div key={idx} className="h-3" />;

          // 去掉模型输出里的 Markdown # 符号（如 #####）
          const withoutHashes = t.replace(/^#{1,6}\s*/, "").trim();
          if (!withoutHashes) return <div key={idx} className="h-2" />;

          if (/^[\-•]/.test(withoutHashes)) return <div key={idx} className="pl-3">• {withoutHashes.replace(/^[\-•]\s*/, "")}</div>;
          return <p key={idx} className="my-0">{withoutHashes}</p>;
        })}
      </article>
    );
  };

  const getSourceMark = (source: string) => {
    const s = String(source || "").trim();
    if (s.includes("指定产品ID")) return "指";
    if (s.includes("异动")) return "异";
    if (s.includes("新发")) return "新";
    return "";
  };

  const renderTable = (rows: OptimizeRow[], emptyText: string) => (
    <div className="h-[620px] overflow-auto rounded-lg border border-border/50">
      <table className="min-w-full text-sm">
        <thead className="sticky top-0 bg-muted/90">
          <tr className="border-b bg-muted/90">
            <th className="text-left py-2 px-3 text-xs">产品ID</th>
            <th className="text-left py-2 px-3 text-xs">原标题</th>
            <th className="text-left py-2 px-3 text-xs">优化后的标题</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={3} className="py-8 text-center text-xs text-muted-foreground">{emptyText}</td></tr>
          ) : rows.map((r, i) => {
            const sourceMark = getSourceMark(r.source);
            return (
              <tr key={`${r.product_id}-${i}`} className="border-b last:border-0 hover:bg-accent/30">
                <td className="py-2 px-3 text-xs font-mono whitespace-nowrap">
                  <button type="button" className="inline-flex items-center gap-2 text-left cursor-pointer" onClick={() => openDetail(r)}>
                    <span>{r.product_id}</span>
                    {sourceMark ? (
                      <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-slate-200 text-[10px] font-semibold text-slate-700">
                        {sourceMark}
                      </span>
                    ) : null}
                  </button>
                </td>
                <td className="py-2 px-3 text-xs whitespace-pre-wrap leading-6">
                  <button type="button" className="w-full text-left cursor-pointer select-text" onClick={() => openDetail(r)}>
                    {r.original_title || "-"}
                  </button>
                </td>
                <td className="py-2 px-3 text-xs">
                  <div className="whitespace-pre-wrap leading-6 select-text">{r.suggested_title ? formatTitleVersions(r.suggested_title) : (r.error ? `失败：${r.error}` : "-")}</div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );

  return (
    <div className="p-8 space-y-6">
      <div>
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>数据分析</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">产品优化建议</span>
        </div>
        <h1 className="text-2xl font-bold text-foreground">产品优化建议</h1>
        <p className="text-sm text-muted-foreground mt-1">结合异动产品 + 新品(7-30天) + 指定产品ID，自动生成标题优化建议</p>
      </div>

      <div className="grid grid-cols-12 gap-6 items-start">
        <div className="col-span-8 space-y-6">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">分析结果</CardTitle>
            </CardHeader>
            <CardContent>
              {renderTable(
                allRows,
                hasResults ? "暂无分析结果" : "当前没有加载到数据，请检查后端结果文件或点击右上角刷新"
              )}
            </CardContent>
          </Card>
        </div>

        <div className="col-span-4">
          <Card className="sticky top-6">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">配置模块</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {isAdminSession && (
                <>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">API_KEY</Label>
                <Input
                  type="text"
                  value={isApiKeyEditing ? apiKeyEditing : apiKey}
                  onFocus={() => {
                    setIsApiKeyEditing(true);
                    setApiKeyEditing(apiKey);
                  }}
                  onChange={(e) => {
                    setIsApiKeyEditing(true);
                    setApiKeyEditing(e.target.value);
                  }}
                  onBlur={() => {
                    const final = String(apiKeyEditing || "").trim();
                    setApiKey(final);
                    setApiKeyEditing(final);
                    setIsApiKeyEditing(false);
                  }}
                  className="text-sm font-mono"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">模型名称</Label>
                <Input value={modelName} onChange={(e) => setModelName(e.target.value)} className="text-sm" />
              </div>
                </>
              )}
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">结果文件路径</Label>
                <Input value={resultFile} onChange={(e) => setResultFile(e.target.value)} className="text-sm font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">详情TXT目录</Label>
                <Input value={detailDir} onChange={(e) => setDetailDir(e.target.value)} className="text-sm font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">指定产品ID（可选，逗号分隔）</Label>
                <div className="flex items-center gap-2">
                  <Input
                    value={manualIds}
                    onChange={(e) => setManualIds(e.target.value)}
                    placeholder="例如：1601234567890,1601234567891"
                    className="text-sm font-mono"
                  />
                  <Button size="sm" variant="outline" onClick={() => {
                    setPickerSource("all");
                    setPickerOpen(true);
                  }}>选择产品</Button>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" variant="outline" onClick={saveConfig}>保存配置</Button>
                <Button size="sm" variant="outline" onClick={refreshResults}>刷新结果</Button>
                <Button
                  size="sm"
                  variant={isRunning ? "destructive" : "default"}
                  onClick={isRunning ? stopAnalyze : startAnalyze}
                  className="gap-2"
                >
                  <Wand2 className="w-4 h-4" />
                  {isRunning ? "停止分析" : "开始分析"}
                </Button>
              </div>

              <div className="text-xs text-muted-foreground">
                优化产品列表会自动加载并定时刷新，点击“开始分析”后优先分析异动明细中全店曝光为负数的产品。
                {!isAdminSession ? (
                  <>
                    <br />
                    每条成功生成建议扣 {pointsPerItem} 积分
                    {pointsEstimate?.cloud_unavailable ? (
                      <> · <span className="text-amber-700">{pointsEstimate.points_error || "云端积分暂不可用"}</span></>
                    ) : pointsEstimate && pointsEstimate.skip_points !== true ? (
                      ` · 余额 ${pointsEstimate.balance ?? 0}${
                          pointsEstimate.planned_items > 0
                            ? ` · 预计约 ${pointsEstimate.estimated_total_cost ?? (pointsEstimate.planned_items * pointsPerItem).toFixed(2)} 积分（${pointsEstimate.planned_items} 条）`
                            : ""
                        }`
                    ) : null}
                  </>
                ) : null}
              </div>

              <div className="text-xs text-muted-foreground">最近生成：{results.generated_at || "-"}</div>
              <div className="rounded-md border border-dashed border-border/60 bg-muted/20 px-3 py-2 text-xs leading-5 text-muted-foreground">
                <div>{runMessage || "当前状态：未知"}</div>
                {runError ? <div className="mt-1 text-destructive">错误：{runError}</div> : null}
              </div>

              <div className="rounded-md border border-border/60 bg-muted/30 p-3 text-xs text-muted-foreground leading-6">
                产品首图来源：自动使用“店铺图片采集”保存目录下的产品图片；
                产品标题来源：自动从该目录下的“产品标题.xlsx”按产品ID读取；
                关键词数据来源：自动从“产品360 Excel结果”最新文件的“关键词”sheet读取，按“搜索点击次数”&gt;=1 / =0 分组。
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="w-[66vw] max-w-[66vw] sm:!max-w-[66vw] h-[82vh] p-0 overflow-hidden">
          <DialogHeader className="px-7 pt-5 pb-3 border-b bg-muted/30">
            <DialogTitle className="text-base">{dialogTitle}</DialogTitle>
          </DialogHeader>
          <div className="h-full overflow-auto px-8 py-6 bg-background">
            <div className="rounded-xl border border-border/60 bg-card p-6 shadow-sm">
              {renderMarkdownLike(dialogContent)}
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
        <DialogContent className="w-[66vw] max-w-[66vw] sm:!max-w-[66vw] h-[82vh] p-0 overflow-hidden">
          <DialogHeader className="px-6 pt-5 pb-3 border-b bg-muted/30">
            <DialogTitle className="text-base">选择产品</DialogTitle>
          </DialogHeader>
          <div className="px-6 py-3 border-b bg-background space-y-3">
            <div className="flex items-center gap-3">
              <span className="text-xs text-muted-foreground whitespace-nowrap">选择来源</span>
              <div className="flex flex-wrap gap-2">
                {[
                  { key: "anomaly", label: "产品异动" },
                  { key: "new", label: "新品" },
                  { key: "all", label: "全部产品" },
                ].map((item) => (
                  <Button
                    key={item.key}
                    size="sm"
                    variant={pickerSource === item.key ? "default" : "outline"}
                    onClick={() => setPickerSource(item.key as any)}
                  >
                    {item.label}
                  </Button>
                ))}
              </div>
            </div>
            {pickerSource === "all" && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">数据sheet</span>
                <select
                  className="h-8 rounded border border-input bg-background px-2 text-xs"
                  value={pickerSheet}
                  onChange={(e) => setPickerSheet(e.target.value)}
                >
                  {["全店曝光次数", "搜索曝光次数", "全店点击次数", "访问人数", "询盘人数", "TM咨询人数", "收藏人数", "全站推广曝光次数", "全站推广点击次数"].map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
            )}
            <div className="flex items-center justify-between gap-3">
              <div className="text-xs text-muted-foreground">
                {pickerSource === "anomaly" ? "仅可选择全店曝光为负数的产品" : "可按表格勾选产品"}
              </div>
              <div className="flex items-center gap-2">
                <div className="text-xs text-muted-foreground">已选 {pickerSelectedIds.length} 个</div>
                <Button size="sm" variant="outline" onClick={() => setPickerSelectedIds([])}>清空选择</Button>
                <Button size="sm" onClick={confirmPick}>确认选择</Button>
              </div>
            </div>
          </div>

          <div className="h-full overflow-auto p-4 bg-background">
            <div className="h-full overflow-auto rounded-lg border border-border/50">
              {pickerLoading ? (
                <div className="py-10 text-center text-xs text-muted-foreground">加载中...</div>
              ) : (
                <table className="min-w-max text-sm">
                  <thead className="sticky top-0 bg-muted/90 z-10">
                    <tr className="border-b bg-muted/90">
                      {(pickerCols.length ? pickerCols : ["产品ID"]).map((c) => (
                        <th
                          key={c}
                          className="text-left py-2 px-3 text-xs font-medium text-muted-foreground whitespace-nowrap cursor-pointer select-none"
                          onClick={() => onPickerSort(c)}
                        >
                          {(pickerSource === "anomaly" ? (ANOMALY_COL_LABELS[c] || c) : c)}
                          {pickerSortMark(c) ? ` ${pickerSortMark(c)}` : ""}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(pickerDisplayRows || []).map((r: any, idx: number) => {
                      const pid = normalizePid(r?.["产品ID"] ?? r?.productId);
                      const selected = pid && pickerSelectedIds.includes(pid);
                      const analyzed = (() => {
                        if (!pid) return false;
                        const rowHit = (allRows || []).some((x) => normalizePid(x?.product_id) === pid);
                        if (!rowHit) return false;
                        return !!resultDataVersion && resultDataVersion === pickerDataVersion;
                      })();
                      const canPick = true;
                      return (
                        <tr
                          key={`pick-${idx}`}
                          className={`border-b last:border-0 cursor-pointer ${selected ? "bg-green-100 hover:bg-green-100" : analyzed ? "bg-red-100/85 hover:bg-red-100" : "hover:bg-accent/30"}`}
                          onClick={() => {
                            if (!canPick) return;
                            togglePick(r?.["产品ID"] ?? r?.productId);
                          }}
                        >
                          {(pickerCols.length ? pickerCols : ["产品ID"]).map((c) => (
                            <td key={c} className="py-2 px-3 text-xs whitespace-nowrap">{String(r?.[c] ?? r?.[c === "productId" ? "产品ID" : c] ?? "")}</td>
                          ))}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
