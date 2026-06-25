import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight, Wand2, Settings, FolderOutput, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { analysisApi, configApi, uploadApi } from "@/lib/api";

const FAILURE_ID_KEY = "optimize_failed_product_ids";

type OptimizeListRow = {
  product_id: string;
  optimize_date: string;
  title_before: string;
  title_after: string;
  attrs: string[];
  history: Array<{ week: string; value: string }>;
  is_new_product?: boolean;
};

type RecentOptimizeConflict = {
  product_id: string;
  last_optimize_date: string;
  days_ago: number;
};

export default function OptimizeProduct() {
  const [manualIds, setManualIds] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const wasRunningRef = useRef(false);
  const [currentStep, setCurrentStep] = useState("");
  const [progressText, setProgressText] = useState("0/0");

  const [outputDir, setOutputDir] = useState("");
  const [attrNamesText, setAttrNamesText] = useState("");
  const [autoSubmit, setAutoSubmit] = useState(false);

  const [optimizeList, setOptimizeList] = useState<OptimizeListRow[]>([]);
  const [historyWeeks, setHistoryWeeks] = useState<string[]>([]);
  const [optSearch, setOptSearch] = useState("");
  const [optSortKey, setOptSortKey] = useState<"product_id" | "optimize_date">("optimize_date");
  const [optSortDir, setOptSortDir] = useState<"asc" | "desc">("desc");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmConflicts, setConfirmConflicts] = useState<RecentOptimizeConflict[]>([]);
  const [pendingStartIds, setPendingStartIds] = useState("");
  const [confirmCountdown, setConfirmCountdown] = useState(20);
  const [failedOptimizeIds, setFailedOptimizeIds] = useState<string[]>([]);

  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerLoading, setPickerLoading] = useState(false);
  const [pickerSource, setPickerSource] = useState<"anomaly" | "new" | "all">("all");
  const [pickerSheet, setPickerSheet] = useState("全店曝光次数");
  const [pickerCols, setPickerCols] = useState<string[]>([]);
  const [pickerRows, setPickerRows] = useState<any[]>([]);
  const [pickerSelectedIds, setPickerSelectedIds] = useState<string[]>([]);
  const [pickerSortKey, setPickerSortKey] = useState<string>("产品ID");
  const [pickerSortDir, setPickerSortDir] = useState<"asc" | "desc">("asc");

  const normalizePid = (v: any) => {
    const s = String(v ?? "").replace(/\.0+$/, "").trim();
    if (!s) return "";
    const byParam = s.match(/(?:itemId=|productId=|id=)(\d{10,20})/i);
    if (byParam) return byParam[1];
    const arr = s.match(/\d{10,20}/g);
    if (arr && arr.length) return arr.sort((a, b) => b.length - a.length)[0];
    return s;
  };

  const refreshStatus = useCallback(async () => {
    try {
      const res: any = await uploadApi.getOptimizeStatus();
      const payload = res?.data || res;
      const data = payload?.data || payload || {};
      const s = String(data?.status || "idle");
      const runningNow = s === "running" || s === "paused" || s === "stopping";

      // 任务从运行态结束后，自动清空手动产品ID
      if (wasRunningRef.current && !runningNow) {
        setManualIds("");
        setPickerSelectedIds([]);
      }
      wasRunningRef.current = runningNow;

      setIsRunning(runningNow);
      setCurrentStep(runningNow ? String(data?.current_step || "") : "");
      setProgressText(runningNow ? `${Number(data?.progress || 0)}/${Number(data?.total || 0)}` : "0/0");
    } catch {
      // ignore
    }
  }, []);

  const refreshOptimizeList = useCallback(async () => {
    try {
      const res: any = await uploadApi.getOptimizeList({ limit: 300 });
      const payload = res?.data || res;
      const data = payload?.data || payload || {};
      setOptimizeList(Array.isArray(data?.rows) ? data.rows : []);
      setHistoryWeeks(Array.isArray(data?.history_weeks) ? data.history_weeks : []);
    } catch {
      // ignore
    }
  }, []);

  const refreshFailedOptimizeIds = useCallback(async () => {
    try {
      const res: any = await uploadApi.getOptimizeFailedToday();
      const payload = res?.data || res;
      const data = payload?.data || payload || {};
      const ids = Array.isArray(data?.ids)
        ? data.ids.map((x: any) => normalizePid(x)).filter((pid: string): pid is string => !!pid)
        : [];
      setFailedOptimizeIds(ids);
      try {
        window.localStorage.setItem(FAILURE_ID_KEY, JSON.stringify(ids));
      } catch {
        // ignore
      }
    } catch {
      try {
        const cached = window.localStorage.getItem(FAILURE_ID_KEY);
        setFailedOptimizeIds(cached ? (JSON.parse(cached) as string[]) : []);
      } catch {
        // ignore
      }
    }
  }, []);

  const refreshAll = useCallback(async () => {
    await Promise.all([refreshStatus(), refreshOptimizeList()]);
  }, [refreshOptimizeList, refreshStatus]);

  const loadConfig = useCallback(async () => {
    try {
      const upload = (await configApi.getSection("upload")) || {};
      setOutputDir(String(upload?.optimize_output_dir || ""));
      setAttrNamesText(String(upload?.optimize_attribute_names || ""));
      setAutoSubmit(!!upload?.optimize_auto_submit);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    loadConfig();
    refreshAll();
    refreshFailedOptimizeIds();
    const t = window.setInterval(() => {
      refreshAll();
      refreshFailedOptimizeIds();
    }, 2500);
    return () => window.clearInterval(t);
  }, [loadConfig, refreshAll, refreshFailedOptimizeIds]);

  const handleSaveConfig = useCallback(async () => {
    try {
      const current = (await configApi.getSection("upload")) || {};
      await configApi.updateSection("upload", {
        ...current,
        optimize_output_dir: String(outputDir || "").trim(),
        optimize_attribute_names: String(attrNamesText || "").trim(),
        optimize_auto_submit: !!autoSubmit,
      });
      toast.success("优化产品配置已保存");
    } catch (e: any) {
      toast.error(e?.message || "保存配置失败");
    }
  }, [attrNamesText, outputDir, autoSubmit]);

  const calcDaysAgo = (dateStr: string) => {
    const s = String(dateStr || "").trim();
    if (!s) return Number.POSITIVE_INFINITY;
    const t = new Date(`${s}T00:00:00`).getTime();
    if (!Number.isFinite(t)) return Number.POSITIVE_INFINITY;
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    return Math.floor((today - t) / (24 * 60 * 60 * 1000));
  };

  const findRecentConflicts = (ids: string[]): RecentOptimizeConflict[] => {
    const seen = new Set<string>();
    const out: RecentOptimizeConflict[] = [];
    for (const pid of ids) {
      if (!pid || seen.has(pid)) continue;
      seen.add(pid);
      const latest = optimizeList.find((r) => String(r.product_id) === String(pid));
      if (!latest?.optimize_date) continue;
      const days = calcDaysAgo(latest.optimize_date);
      if (days >= 0 && days < 7) {
        out.push({ product_id: pid, last_optimize_date: latest.optimize_date, days_ago: days });
      }
    }
    return out;
  };

  const startOptimizeDirectly = async (idsText: string) => {
    await uploadApi.startOptimize({ manual_product_ids: idsText || undefined });
    toast.success("优化产品任务已启动");
    setIsRunning(true);
    await refreshStatus();
    await refreshOptimizeList();
  };

  const handleStart = useCallback(async () => {
    try {
      const selectedIds = pickerSelectedIds.length ? pickerSelectedIds.join(",") : "";
      const finalIds = String(selectedIds || manualIds || "").trim();
      const ids = finalIds
        ? finalIds.split(",").map((x) => normalizePid(x)).filter(Boolean)
        : [];

      if (pickerSource === "anomaly") {
        const anomalyIds = Array.from(
          new Set(
            (pickerRows || [])
              .filter((row: any) => Number(String(row?.shopExposure ?? 0).replace(/,/g, "")) < 0)
              .map((row: any) => normalizePid(row?.productId || row?.产品ID))
              .filter(Boolean)
          )
        );
        const anomalySet = new Set(anomalyIds);
        const filteredIds = ids.filter((id) => anomalySet.has(id));
        if (!filteredIds.length) {
          toast.info("当前来源为产品异动，请先选择全店曝光为负数的产品");
          return;
        }
        await startOptimizeDirectly(filteredIds.join(","));
        return;
      }

      if (ids.length) {
        const conflicts = findRecentConflicts(ids);
        if (conflicts.length) {
          const conflictSet = new Set(conflicts.map((c) => c.product_id));
          const remainIds = ids.filter((id) => !conflictSet.has(id));

          setPendingStartIds(remainIds.join(","));
          setConfirmConflicts(conflicts);
          setConfirmCountdown(20);
          setConfirmOpen(true);
          return;
        }
      }

      await startOptimizeDirectly(finalIds);
    } catch (e: any) {
      toast.error(e?.message || "启动失败");
    }
  }, [manualIds, pickerSelectedIds, optimizeList, pickerSource, pickerRows]);

  const handleOpenPicker = useCallback(() => {
    setPickerSelectedIds(manualIds.split(",").map((x) => normalizePid(x)).filter(Boolean));
    setPickerSource("all");
    setPickerOpen(true);
  }, [manualIds]);

  const handleStop = useCallback(async () => {
    try {
      try {
        await uploadApi.stopOptimize();
        toast.info("优化产品任务已停止");
      } catch (e: any) {
        const msg = String(e?.message || e?.detail || "");
        if (!msg.includes("没有正在运行")) {
          throw e;
        }
        toast.info("任务已结束，已同步最新状态");
      }

      // 无论服务端是“正在停止中”还是已经完全结束，前端先恢复为可操作状态，
      // 再通过轮询同步最终状态，避免按钮卡在“停止中/运行中”。
      setIsRunning(false);
      setCurrentStep("");
      setProgressText("0/0");
      wasRunningRef.current = false;
      await refreshStatus();
    } catch (e: any) {
      toast.error(e?.message || "停止失败");
    }
  }, [refreshStatus]);

  useEffect(() => {
    if (!confirmOpen) return;

    setConfirmCountdown(20);
    const timer = window.setInterval(() => {
      setConfirmCountdown((prev) => {
        if (prev <= 1) {
          window.clearInterval(timer);
          setConfirmOpen(false);
          const idsText = String(pendingStartIds || "").trim();
          if (idsText) {
            startOptimizeDirectly(idsText).catch((e: any) => {
              toast.error(e?.message || "启动失败");
            });
          } else {
            toast.info("检测到近7天重复优化产品，20秒未确认，已全部跳过");
          }
          setPendingStartIds("");
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => window.clearInterval(timer);
  }, [confirmOpen, pendingStartIds]);

  const loadPickerData = async (source = pickerSource) => {
    setPickerLoading(true);
    try {
      const da = (await configApi.getSection("data_analysis")) || {};
      const outputFile = da.output_file || undefined;
      const newOutputFile = da.new_output_file || undefined;
      const volatilityPath = da.volatility_file_path || undefined;

      let colsRaw: string[] = [];
      let rows: any[] = [];

      if (source === "anomaly") {
        const res: any = await analysisApi.getVolatilityAnomaly(volatilityPath || undefined);
        const payload = res?.data || res;
        const data = payload?.data || payload;
        colsRaw = ["productId", "shopExposure", "p4pExposure", "searchExposure", "naturalExposure", "sceneExposure", "shopClicks", "p4pClicks", "searchClicks", "naturalClicks", "sceneClicks"];
        rows = Array.isArray(data?.rows) ? data.rows : [];
      } else if (source === "new") {
        const res: any = await analysisApi.getNewLinksMonitor(newOutputFile || undefined, "全店曝光次数");
        const payload = res?.data || res;
        const data = payload?.data || payload;
        colsRaw = Array.isArray(data?.columns) ? (data.columns as any[]).map((x) => String(x ?? "")) : [];
        rows = Array.isArray(data?.rows) ? data.rows : [];
      } else {
        const res: any = await analysisApi.getStatisticsTable(outputFile || undefined, pickerSheet);
        const payload = res?.data || res;
        const data = payload?.data || payload;
        colsRaw = Array.isArray(data?.columns)
          ? (data.columns as any[]).map((x) => String(x ?? ""))
          : [];
        rows = Array.isArray(data?.rows) ? data.rows : [];
      }

      const isWeekCol = (c: string) => /^\d{6}-\d{6}$/.test(String(c));
      const weekCols = colsRaw.filter(isWeekCol).sort((a, b) => String(b).localeCompare(String(a)));
      const nonWeekCols = colsRaw.filter((c) => !isWeekCol(c));
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

  useEffect(() => {
    if (!pickerOpen) return;
    loadPickerData(pickerSource);
  }, [pickerOpen, pickerSource, pickerSheet]);

  const onPickerSort = (c: string) => {
    if (pickerSortKey === c) {
      setPickerSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setPickerSortKey(c);
      setPickerSortDir(c === "产品ID" ? "asc" : "desc");
    }
  };
  const pickerSortMark = (c: string) => (pickerSortKey === c ? (pickerSortDir === "asc" ? "↑" : "↓") : "");

  const pickerDisplayRows = useMemo(() => {
    const rows = [...(pickerRows || [])];
    const key = pickerSortKey;
    if (!key) return rows;

    const isWeekCol = /^\d{6}-\d{6}$/.test(String(key));
    rows.sort((a: any, b: any) => {
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

      const as = String(avRaw ?? "");
      const bs = String(bvRaw ?? "");
      return pickerSortDir === "asc" ? as.localeCompare(bs) : bs.localeCompare(as);
    });
    return rows;
  }, [pickerRows, pickerSortKey, pickerSortDir]);

  const togglePick = (pidRaw: any) => {
    const pid = normalizePid(pidRaw);
    if (!pid) return;
    setPickerSelectedIds((prev) => (prev.includes(pid) ? prev.filter((x) => x !== pid) : [...prev, pid]));
  };

  const renderPickerSourceLabel = () => {
    if (pickerSource === "anomaly") return "产品异动";
    if (pickerSource === "new") return "新品";
    return "全部产品";
  };

  const onOptimizeSort = (key: "product_id" | "optimize_date") => {
    if (optSortKey === key) {
      setOptSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setOptSortKey(key);
      setOptSortDir(key === "optimize_date" ? "desc" : "asc");
    }
  };

  const optimizeSortMark = (key: "product_id" | "optimize_date") =>
    optSortKey === key ? (optSortDir === "asc" ? "↑" : "↓") : "";

  const sortedOptimizeList = useMemo(() => {
    const q = String(optSearch || "").trim().toLowerCase();

    let rows = [...(optimizeList || [])];
    if (q) {
      rows = rows.filter((r) => {
        const pid = String(r?.product_id || "").toLowerCase();
        const titleBefore = String(r?.title_before || "").toLowerCase();
        const titleAfter = String(r?.title_after || "").toLowerCase();
        const attrs = Array.isArray(r?.attrs) ? r.attrs.join(" ").toLowerCase() : "";
        return pid.includes(q) || titleBefore.includes(q) || titleAfter.includes(q) || attrs.includes(q);
      });
    }

    rows.sort((a, b) => {
      if (optSortKey === "product_id") {
        const ap = normalizePid(a?.product_id);
        const bp = normalizePid(b?.product_id);
        return optSortDir === "asc" ? ap.localeCompare(bp) : bp.localeCompare(ap);
      }

      const at = new Date(`${String(a?.optimize_date || "")}T00:00:00`).getTime();
      const bt = new Date(`${String(b?.optimize_date || "")}T00:00:00`).getTime();
      const an = Number.isFinite(at) ? at : -Infinity;
      const bn = Number.isFinite(bt) ? bt : -Infinity;
      return optSortDir === "asc" ? an - bn : bn - an;
    });
    return rows;
  }, [optimizeList, optSortKey, optSortDir, optSearch]);

  const confirmPick = () => {
    setManualIds(pickerSelectedIds.join(","));
    setPickerOpen(false);
  };

  const clearPickerSelection = useCallback(() => {
    setPickerSelectedIds([]);
    setManualIds("");
  }, []);

  return (
    <div className="p-8 space-y-6">
      <div>
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>产品上传</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">优化产品</span>
        </div>
        <h1 className="text-2xl font-bold text-foreground">优化产品</h1>
        <p className="text-sm text-muted-foreground mt-1">
          选择产品并回填优化标题、属性埋词、卖点埋词，最终导出 Excel
        </p>
      </div>

      <div className="grid grid-cols-12 gap-6 items-start">
        <div className="col-span-8 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">任务配置</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">指定产品ID（可选，逗号分隔）</Label>
                <div className="flex items-center gap-2">
                  <Input
                    value={manualIds}
                    onChange={(e) => setManualIds(e.target.value)}
                    placeholder="例如：1601711190204,1601711190205"
                    className="font-mono"
                  />
                  <Button variant="outline" onClick={handleOpenPicker}>选择产品</Button>
                </div>
                <p className="text-xs text-muted-foreground">留空则默认使用“产品优化建议”结果中的产品列表。注：单个产品优化时以7天为一周期，观察数据变化</p>
              </div>

              <div className="flex items-center gap-2">
                {!isRunning ? (
                  <Button onClick={handleStart} className="gap-2">
                    <Wand2 className="w-4 h-4" />
                    开始优化
                  </Button>
                ) : (
                  <Button variant="destructive" onClick={handleStop}>停止优化</Button>
                )}
                <Badge variant={isRunning ? "default" : "secondary"}>{isRunning ? "运行中" : "待启动"}</Badge>
                <span className="text-xs text-muted-foreground">进度：{progressText}</span>
              </div>

              {!!currentStep && (
                <div className="text-xs text-muted-foreground bg-muted/50 rounded-md px-3 py-2">
                  当前：{currentStep}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="text-base">优化产品列表</CardTitle>
                <div className="w-[280px]">
                  <Input
                    value={optSearch}
                    onChange={(e) => setOptSearch(e.target.value)}
                    placeholder="搜索产品ID/标题/属性"
                    className="h-8 text-xs font-mono"
                  />
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="mb-3 rounded-lg border border-dashed border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">
                <span className="mr-2 font-medium">未优化成功的产品ID：</span>
                <span className="font-mono text-red-800">
                  {failedOptimizeIds.length ? failedOptimizeIds.join(", ") : "暂无"}
                </span>
              </div>
              <div className="rounded-lg border border-border/50 h-[560px] overflow-auto">
                <table className="min-w-full text-sm">
                  <thead className="bg-muted/60">
                    <tr className="border-b">
                      <th
                        className="text-left py-2 px-3 text-xs font-medium text-muted-foreground cursor-pointer select-none"
                        onClick={() => onOptimizeSort("product_id")}
                      >
                        产品ID{optimizeSortMark("product_id") ? ` ${optimizeSortMark("product_id")}` : ""}
                      </th>
                      <th
                        className="text-left py-2 px-3 text-xs font-medium text-muted-foreground cursor-pointer select-none"
                        onClick={() => onOptimizeSort("optimize_date")}
                      >
                        优化时间{optimizeSortMark("optimize_date") ? ` ${optimizeSortMark("optimize_date")}` : ""}
                      </th>
                      <th className="text-left py-2 px-3 text-xs font-medium text-muted-foreground">优化标题</th>
                      <th className="text-left py-2 px-3 text-xs font-medium text-muted-foreground">优化属性</th>
                      <th className="text-left py-2 px-3 text-xs font-medium text-muted-foreground">历史数据</th>
                      <th className="text-left py-2 px-3 text-xs font-medium text-muted-foreground">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedOptimizeList.map((row, idx) => {
                      const prevSameProduct = sortedOptimizeList.slice(idx + 1).find((r) => r.product_id === row.product_id);
                      return (
                        <tr key={`${row.product_id}-${idx}`} className="border-b last:border-0 align-top">
                          <td className="py-2 px-3 text-xs font-mono whitespace-nowrap">
                            <span className="inline-flex items-center gap-2">
                              <span>{row.product_id}</span>
                              {row.is_new_product ? (
                                <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-green-500 text-[10px] font-medium text-white">新</span>
                              ) : null}
                            </span>
                          </td>
                          <td className="py-2 px-3 text-xs whitespace-nowrap">{row.optimize_date || "-"}</td>
                          <td className="py-2 px-3 text-xs">
                            <div className="whitespace-pre-wrap leading-5">
                              <div>原标题：{row.title_before || "-"}</div>
                              <div>优化后：{row.title_after || "-"}</div>
                            </div>
                          </td>
                          <td className="py-2 px-3 text-xs">
                            <div className="whitespace-pre-wrap leading-5">
                              {(row.attrs || []).length ? row.attrs.map((a, i) => <div key={i}>{a}</div>) : <div>-</div>}
                            </div>
                          </td>
                          <td className="py-2 px-3 text-xs">
                            {!historyWeeks.length ? (
                              <div className="text-muted-foreground">-</div>
                            ) : (
                              <div className="space-y-1">
                                {historyWeeks.map((wk) => {
                                  const cur = (row.history || []).find((h) => h.week === wk)?.value ?? "";
                                  const prev = prevSameProduct ? ((prevSameProduct.history || []).find((h) => h.week === wk)?.value ?? "") : "";
                                  const updated = prevSameProduct ? String(cur) !== String(prev) : false;
                                  return (
                                    <div
                                      key={wk}
                                      className={`grid grid-cols-[110px_1fr] gap-2 rounded border px-2 py-1 ${updated ? "bg-green-100 border-green-300" : "bg-background"}`}
                                      title={wk}
                                    >
                                      <span className="text-[10px] text-muted-foreground">{wk}</span>
                                      <span className="text-xs">{String(cur || "-")}</span>
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </td>
                          <td className="py-2 px-3 text-xs whitespace-nowrap">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 px-2 text-red-600 hover:text-red-700 hover:bg-red-50"
                              onClick={async () => {
                                try {
                                  await uploadApi.deleteOptimizeRecord({ product_id: row.product_id, optimize_date: row.optimize_date });
                                  toast.success(`已删除产品 ${row.product_id}`);
                                  await refreshOptimizeList();
                                  await refreshFailedOptimizeIds();
                                } catch (e: any) {
                                  toast.error(e?.message || "删除失败");
                                }
                              }}
                            >
                              <Trash2 className="w-4 h-4 mr-1" />
                              删除
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                    {!sortedOptimizeList.length && (
                      <tr>
                        <td className="py-6 px-3 text-center text-xs text-muted-foreground" colSpan={5}>暂无优化记录</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="col-span-4">
          <Card className="sticky top-6">
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <Settings className="w-4 h-4" />
                配置模块
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">输出目录</Label>
                <div className="flex items-center gap-2">
                  <FolderOutput className="w-4 h-4 text-muted-foreground" />
                  <Input value={outputDir} onChange={(e) => setOutputDir(e.target.value)} className="text-sm font-mono" />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">需要埋词的属性</Label>
                <Input
                  value={attrNamesText}
                  onChange={(e) => setAttrNamesText(e.target.value)}
                  className="text-sm"
                  placeholder="例如：特性,应用场景,型号,使用"
                />
                <p className="text-[11px] text-muted-foreground leading-5">
                  系统会把“属性埋词推荐”清洗后的关键词全部均分到这些属性中，填写前会清空原值。
                </p>
              </div>

              <div className="flex items-center justify-between rounded-md border border-border/60 px-3 py-2">
                <div>
                  <div className="text-xs text-foreground">自动提交</div>
                  <div className="text-[11px] text-muted-foreground">开启后会在填写完成后点击提交并校验结果</div>
                </div>
                <Switch checked={autoSubmit} onCheckedChange={setAutoSubmit} />
              </div>

              <Button variant="outline" onClick={handleSaveConfig}>保存配置</Button>
            </CardContent>
          </Card>
        </div>
      </div>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="sm:max-w-[620px] p-0 overflow-hidden">
          <div className="bg-gradient-to-r from-amber-50 to-orange-50 border-b px-6 py-4">
            <DialogHeader>
              <DialogTitle className="text-[17px] font-semibold text-amber-900">该产品7天内优化过，是否继续优化？</DialogTitle>
            </DialogHeader>
            <p className="text-xs text-amber-800 mt-1.5">
              为避免短期重复优化影响判断，系统检测到以下产品在近7天已有优化记录。若 {confirmCountdown} 秒内未操作，将自动跳过这些产品并继续优化其他产品。
            </p>
          </div>

          <div className="px-6 py-4 space-y-3 max-h-[320px] overflow-auto">
            {confirmConflicts.map((c) => (
              <div key={c.product_id} className="rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2.5">
                <div className="text-sm font-medium text-foreground">产品ID：<span className="font-mono">{c.product_id}</span></div>
                <div className="text-xs text-muted-foreground mt-1">
                  最近优化时间：<span className="text-foreground">{c.last_optimize_date}</span>
                  <span className="mx-1">·</span>
                  距今 <span className="text-foreground">{c.days_ago}</span> 天
                </div>
              </div>
            ))}
          </div>

          <div className="px-6 py-4 border-t bg-muted/20 flex items-center justify-end gap-2">
            <Button
              variant="outline"
              onClick={() => {
                setConfirmOpen(false);
                setPendingStartIds("");
              }}
            >
              取消
            </Button>
            <Button
              className="bg-amber-600 hover:bg-amber-700 text-white"
              onClick={async () => {
                try {
                  const idsText = String(pendingStartIds || "").trim();
                  setConfirmOpen(false);
                  await startOptimizeDirectly(idsText);
                } catch (e: any) {
                  toast.error(e?.message || "启动失败");
                } finally {
                  setPendingStartIds("");
                }
              }}
            >
              继续优化
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={pickerOpen} onOpenChange={setPickerOpen}>
        <DialogContent className="w-[74vw] max-w-[74vw] sm:!max-w-[74vw] h-[86vh] p-0 overflow-hidden">
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
              <span className="text-xs text-muted-foreground">当前：{renderPickerSourceLabel()}</span>
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
                <Button size="sm" variant="outline" onClick={clearPickerSelection}>清空选择</Button>
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
                  <thead className="sticky top-0 bg-muted z-10">
                    <tr className="border-b bg-muted">
                      {(pickerCols.length ? pickerCols : ["产品ID"]).map((c) => (
                        <th
                          key={c}
                          className="text-left py-2 px-3 text-xs font-medium text-muted-foreground whitespace-nowrap cursor-pointer select-none"
                          onClick={() => onPickerSort(c)}
                        >
                          {c}{pickerSortMark(c) ? ` ${pickerSortMark(c)}` : ""}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(pickerDisplayRows || []).map((r: any, idx: number) => {
                      const pid = normalizePid(r?.["产品ID"] ?? r?.productId);
                      const selected = pid && pickerSelectedIds.includes(pid);
                      const canPick = pickerSource !== "anomaly" || Number(String(r?.shopExposure ?? 0).replace(/,/g, "")) < 0;
                      return (
                        <tr
                          key={`pick-${idx}`}
                          className={`border-b last:border-0 ${canPick ? "cursor-pointer" : "cursor-not-allowed opacity-50"} ${selected ? "bg-green-100 hover:bg-green-100" : "hover:bg-accent/30"}`}
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
