import { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationLink,
  PaginationPrevious,
  PaginationNext,
  PaginationEllipsis,
} from "@/components/ui/pagination";
import { toast } from "sonner";
import { ChevronRight, Pause, Play, RefreshCw, Wand2 } from "lucide-react";
import { configApi, createLogSocket, dataApi, imageApi, uploadApi } from "@/lib/api";

type TitleKeywordRow = {
  source: string;
  keyword: string;
  heat: number;
};

const parseKeywordHeat = (value: any): number => {
  if (typeof value === "number") return Number.isFinite(value) ? value : 0;
  const text = String(value ?? "").replace(/,/g, "").replace(/%/g, "").trim();
  if (!text) return 0;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : 0;
};

export default function IndustryKeyword() {
  const [isRunning, setIsRunning] = useState(false);
  const [dropdownRunning, setDropdownRunning] = useState(false);
  const [logs, setLogs] = useState<string[]>(["[系统] 行业关键词模块已就绪"]);

  const [saveFolder, setSaveFolder] = useState("");
  const [bigKeywords, setBigKeywords] = useState("");
  const [outputFile, setOutputFile] = useState("");
  const [tableQuery, setTableQuery] = useState("");
  const [dropdownQuery, setDropdownQuery] = useState("");
  const [dropdownKeywords, setDropdownKeywords] = useState("");
  const [dropdownOutputFile, setDropdownOutputFile] = useState("");
  const [selectedKeywords, setSelectedKeywords] = useState<string[]>([]);
  const [selectedDropdownRowKeys, setSelectedDropdownRowKeys] = useState<string[]>([]);
  const [titleDialogOpen, setTitleDialogOpen] = useState(false);
  const [titleMode, setTitleMode] = useState<"industry_hot" | "dropdown">("industry_hot");
  const [titleScenes, setTitleScenes] = useState("");
  const [titleMaterial, setTitleMaterial] = useState("");
  const [titleCountPerScene, setTitleCountPerScene] = useState("10");
  const [titleGenerating, setTitleGenerating] = useState(false);
  const [titleResultContent, setTitleResultContent] = useState("");
  const [titleResultRows, setTitleResultRows] = useState<Array<{ scene: string; title: string }>>([]);
  const [titleResultFile, setTitleResultFile] = useState("");
  const [titleSelectedKeywords, setTitleSelectedKeywords] = useState<string[]>([]);
  const [titleSelectedSourcePools, setTitleSelectedSourcePools] = useState<string[]>([]);
  const [titleMinKeywordHeat, setTitleMinKeywordHeat] = useState("0");
  const [titleRunMessage, setTitleRunMessage] = useState("");
  const [titleRunError, setTitleRunError] = useState("");
  const [titleCanResume, setTitleCanResume] = useState(false);
  const [titleProgress, setTitleProgress] = useState({
    completedScenes: 0,
    totalScenes: 0,
    generatedTitles: 0,
    totalTitles: 0,
  });
  const [titleResultPage, setTitleResultPage] = useState(1);
  const [titleResultTotal, setTitleResultTotal] = useState(0);
  const [titleResultTotalPages, setTitleResultTotalPages] = useState(1);
  const titleResultPageRef = useRef(1);
  const titlePollRef = useRef<number | null>(null);
  // 原图目录场景多选弹窗
  const [scenePickerOpen, setScenePickerOpen] = useState(false);
  const [scenePickerList, setScenePickerList] = useState<{ name: string; count: number }[]>([]);
  const [scenePickerSelected, setScenePickerSelected] = useState<string[]>([]);
  const [scenePickerLoading, setScenePickerLoading] = useState(false);

  const [table, setTable] = useState<any>({ columns: [], rows: [], latest_col: "" });
  const [dropdownTable, setDropdownTable] = useState<any>({ columns: [], rows: [], sheet: "", file: "" });
  const lastMainStatusLogRef = useRef("");
  const lastDropdownStatusLogRef = useRef("");
  const lastDropdownProgressRef = useRef(0);
  const prevDropdownRunningRef = useRef(false);
  const wsConnectedRef = useRef(false);

  const taskType = "industry_keyword";
  const dropdownTaskType = "industry_keyword_dropdown";

  const latestCol = useMemo(() => String(table?.latest_col || ""), [table]);
  const filteredRows = useMemo(() => {
    const rows = Array.isArray(table?.rows) ? table.rows : [];
    const columns = Array.isArray(table?.columns) ? table.columns : [];
    if (!rows.length || !columns.length) return [];

    const metricCols = columns.filter((c: string) => c !== "关键词" && c !== "源关键词");
    if (!metricCols.length) return rows;

    const latestMetricCol = latestCol && metricCols.includes(latestCol) ? latestCol : metricCols[0];
    const recentCols = metricCols.slice(0, 5);

    const toNum = (v: any) => {
      if (typeof v === "number") return Number.isFinite(v) ? v : 0;
      const s = String(v ?? "").replace(/,/g, "").trim();
      if (!s) return 0;
      const n = Number(s);
      return Number.isFinite(n) ? n : 0;
    };

    return rows.filter((row: any) => {
      const latestValue = toNum(row?.[latestMetricCol]);
      if (latestValue > 40) return true;

      let hit = 0;
      for (const c of recentCols) {
        if (toNum(row?.[c]) > 40) hit += 1;
      }
      return hit >= 3;
    });
  }, [table, latestCol]);
  const filteredKeywordRows = useMemo(() => {
    const q = tableQuery.trim().toLowerCase();
    if (!q) return filteredRows;
    const cols = Array.isArray(table?.columns) ? table.columns : [];
    return filteredRows.filter((row: any) =>
      cols.some((c: string) => String(row?.[c] ?? "").toLowerCase().includes(q))
    );
  }, [filteredRows, tableQuery, table]);

  const selectedKeywordSet = useMemo(() => new Set(selectedKeywords), [selectedKeywords]);
  const selectedDropdownRowKeySet = useMemo(() => new Set(selectedDropdownRowKeys), [selectedDropdownRowKeys]);
  const dropdownRows = useMemo(() => {
    const rows = Array.isArray(dropdownTable?.rows) ? dropdownTable.rows : [];
    return rows
      .map((row: any) => {
        const origin = String(row?.["原词"] ?? row?.["关键词"] ?? row?.["keyword"] ?? "").trim();
        const suggestion = String(row?.["下拉词"] ?? row?.["US"] ?? row?.["suggestKeyword"] ?? "").trim();
        const source = String(row?.["源关键词"] ?? origin).trim();
        const heat = parseKeywordHeat(row?.["关键词热度"]);
        return { 源关键词: source, 原词: origin, 关键词热度: heat, 下拉词: suggestion };
      })
      .filter((row: any) => row.源关键词 || row.原词 || row.下拉词);
  }, [dropdownTable]);
  const filteredDropdownRows = useMemo(() => {
    const q = dropdownQuery.trim().toLowerCase();
    if (!q) return dropdownRows;
    return dropdownRows.filter((row: any) => {
      const source = String(row?.["源关键词"] ?? "").toLowerCase();
      const origin = String(row?.["原词"] ?? "").toLowerCase();
      const suggestion = String(row?.["下拉词"] ?? "").toLowerCase();
      return source.includes(q) || origin.includes(q) || suggestion.includes(q);
    });
  }, [dropdownRows, dropdownQuery]);

  const industryTitleRows = useMemo<TitleKeywordRow[]>(() => {
    const rows = Array.isArray(table?.rows) ? table.rows : [];
    return rows
      .map((row: any) => {
        const keyword = String(row?.["关键词"] ?? "").trim();
        const source = String(row?.["源关键词"] ?? keyword).trim();
        return { source, keyword, heat: latestCol ? parseKeywordHeat(row?.[latestCol]) : 0 };
      })
      .filter((row: any) => row.source && row.keyword);
  }, [table, latestCol]);
  const dropdownTitleRows = useMemo<TitleKeywordRow[]>(
    () =>
      dropdownRows
        .map((row: any) => ({
          source: String(row?.["源关键词"] ?? row?.["原词"] ?? "").trim(),
          keyword: String(row?.["下拉词"] ?? "").trim(),
          heat: parseKeywordHeat(row?.["关键词热度"]),
        }))
        .filter((row: any) => row.source && row.keyword),
    [dropdownRows]
  );
  const activeTitleRows: TitleKeywordRow[] =
    titleMode === "industry_hot" ? industryTitleRows : dropdownTitleRows;
  const activeSourcePools = useMemo<string[]>(
    () => Array.from(new Set<string>(activeTitleRows.map((row: TitleKeywordRow) => row.source))),
    [activeTitleRows]
  );
  const titleSelectedSourcePoolSet = useMemo(
    () => new Set(titleSelectedSourcePools),
    [titleSelectedSourcePools]
  );
  const parsedTitleMinHeat = parseKeywordHeat(titleMinKeywordHeat);
  const eligibleTitleRows = useMemo<TitleKeywordRow[]>(
    () =>
      activeTitleRows.filter(
        (row: TitleKeywordRow) => titleSelectedSourcePoolSet.has(row.source) && row.heat >= parsedTitleMinHeat
      ),
    [activeTitleRows, titleSelectedSourcePoolSet, parsedTitleMinHeat]
  );
  const activeTitleKeywordDetails = useMemo(() => {
    const detailMap = new Map<string, { keyword: string; sources: string[]; heat: number }>();
    for (const row of eligibleTitleRows) {
      const key = row.keyword.toLowerCase();
      const current = detailMap.get(key);
      if (!current) {
        detailMap.set(key, { keyword: row.keyword, sources: [row.source], heat: row.heat });
        continue;
      }
      if (!current.sources.includes(row.source)) current.sources.push(row.source);
      current.heat = Math.max(current.heat, row.heat);
    }
    return Array.from(detailMap.values()).sort((a, b) => b.heat - a.heat);
  }, [eligibleTitleRows]);
  const activeTitleKeywords = useMemo(
    () => activeTitleKeywordDetails.map((row) => row.keyword),
    [activeTitleKeywordDetails]
  );
  const titleSelectedSet = useMemo(() => new Set(titleSelectedKeywords), [titleSelectedKeywords]);

  useEffect(() => {
    setTitleSelectedSourcePools((prev) => {
      const valid = prev.filter((source) => activeSourcePools.includes(source));
      return valid.length > 0 ? valid : activeSourcePools;
    });
    setTitleSelectedKeywords([]);
  }, [titleMode, activeSourcePools]);

  useEffect(() => {
    // 关键词池或热度变化时，清理掉已经不符合筛选条件的手工选词。
    setTitleSelectedKeywords((prev) => prev.filter((kw) => activeTitleKeywords.includes(kw)));
  }, [activeTitleKeywords]);

  const toggleSelectKeyword = (row: any) => {
    const kw = String(row?.["关键词"] || "").trim();
    if (!kw) return;
    setSelectedKeywords((prev) => {
      const exists = prev.includes(kw);
      if (exists) return prev.filter((x) => x !== kw);
      return [...prev, kw];
    });
  };
  const getDropdownRowKey = (row: any) =>
    `${String(row?.["源关键词"] ?? "").trim()}__${String(row?.["原词"] ?? "").trim()}__${String(row?.["下拉词"] ?? "").trim()}`;
  const toggleSelectDropdownRow = (row: any) => {
    const key = getDropdownRowKey(row);
    if (!key || key === "__") return;
    setSelectedDropdownRowKeys((prev) => (prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]));
  };

  const loadConfig = async () => {
    try {
      const cfg = (await configApi.getSection("industry_keyword")) || {};
      setSaveFolder(String(cfg.save_folder || ""));
      setOutputFile(String(cfg.output_file || ""));
      setDropdownOutputFile(String(cfg.dropdown_output_file || ""));
    } catch (e: any) {
      toast.error(e.message || "加载配置失败");
    }
  };

  const saveConfig = async () => {
    try {
      const current = (await configApi.getSection("industry_keyword")) || {};
      await configApi.updateSection("industry_keyword", {
        ...current,
        save_folder: saveFolder,
        big_keywords: bigKeywords,
        output_file: outputFile,
        dropdown_keywords: dropdownKeywords,
        dropdown_output_file: dropdownOutputFile,
      });
      toast.success("行业关键词配置已保存");
      refreshTable();
    } catch (e: any) {
      toast.error(e.message || "保存失败");
    }
  };

  const appendRuntimeLog = (text: string) => {
    if (!text) return;
    setLogs((prev) => [...prev, text].slice(-500));
  };
  const buildTaskStatusLog = (status: any, label: string) => {
    if (!status) return "";
    if (status?.error) {
      return `[${label}] ${status?.current_step || "执行异常"} | 错误: ${status.error}`;
    }
    return `[${label}] ${status?.current_step || (status?.status || "状态更新")}`;
  };

  const parseKeywordText = (text: string) =>
    Array.from(new Set((text || "").split(/[,，;；\n\r]+/).map((x) => x.trim()).filter(Boolean)));

  const effectiveDropdownKeywords = useMemo(() => {
    const manual = parseKeywordText(dropdownKeywords);
    const selected = Array.isArray(selectedKeywords) ? selectedKeywords : [];
    const merged: string[] = [];
    const seen = new Set<string>();
    for (const kw of [...manual, ...selected]) {
      const value = String(kw || "").trim();
      if (!value) continue;
      const key = value.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      merged.push(value);
    }
    return merged;
  }, [dropdownKeywords, selectedKeywords]);

  const refreshStatus = async (type = taskType) => {
    try {
      const res = await dataApi.getDownloadStatus(type);
      const data = res?.data || res;
      const status = data?.data || data;
      const running = status?.status === "running" || status?.status === "stopping";
      if (type === taskType) {
        setIsRunning(running);
      } else if (type === dropdownTaskType) {
        setDropdownRunning(running);
        // 下拉词任务结束后自动清空选中，恢复表格高亮状态
        if (!running && prevDropdownRunningRef.current) {
          setSelectedKeywords([]);
        }
        prevDropdownRunningRef.current = running;
      }
      return status;
    } catch {
      // ignore
      return null;
    }
  };

  const refreshTable = async () => {
    try {
      const res = await dataApi.getIndustryKeywordLatest(outputFile || undefined);
      const payload = res?.data ?? res;
      const data = payload?.data ?? payload;
      setTable(data || { columns: [], rows: [], latest_col: "" });
    } catch {
      setTable({ columns: [], rows: [], latest_col: "" });
    }
  };

  const refreshDropdownTable = async () => {
    try {
      const res = await dataApi.getIndustryKeywordDropdownLatest(dropdownOutputFile || undefined);
      const payload = res?.data ?? res;
      const data = payload?.data ?? payload;
      setDropdownTable(data || { columns: [], rows: [], sheet: "", file: "" });
    } catch {
      setDropdownTable({ columns: [], rows: [], sheet: "", file: "" });
    }
  };

  const handleStart = async () => {
    try {
      if (!saveFolder.trim()) {
        toast.error("请先配置保存目录");
        return;
      }
      if (!bigKeywords.trim()) {
        toast.error("请先填写行业关键词大词");
        return;
      }
      const current = (await configApi.getSection("industry_keyword")) || {};
      await configApi.updateSection("industry_keyword", {
        ...current,
        save_folder: saveFolder,
        output_file: outputFile,
        dropdown_output_file: dropdownOutputFile,
      });
      setIsRunning(true);
      appendRuntimeLog(`[主任务] 任务启动，共 ${parseKeywordText(bigKeywords).length} 个大词`);
      await dataApi.startDownload({ task_type: taskType, big_keywords: bigKeywords });
      toast.success("行业关键词任务已启动（下载完成后自动整合）");
      refreshStatus(taskType);
    } catch (e: any) {
      setIsRunning(false);
      toast.error(e.message || "启动失败");
    }
  };

  const handleStop = async () => {
    try {
      await dataApi.stopDownload(taskType);
      toast.info("已停止");
      refreshStatus(taskType);
      setIsRunning(false);
    } catch (e: any) {
      toast.error(e.message || "停止失败");
    }
  };

  const handleDropdownStart = async () => {
    try {
      if (!dropdownOutputFile.trim()) {
        toast.error("请先配置下拉词存放路径");
        return;
      }
      if (effectiveDropdownKeywords.length === 0) {
        toast.error("请先配置下拉词关键词，或在左侧表格中选中关键词");
        return;
      }
      const current = (await configApi.getSection("industry_keyword")) || {};
      await configApi.updateSection("industry_keyword", {
        ...current,
        save_folder: saveFolder,
        output_file: outputFile,
        dropdown_output_file: dropdownOutputFile,
      });
      setDropdownRunning(true);
      lastDropdownProgressRef.current = 0;
      lastDropdownStatusLogRef.current = "";
      appendRuntimeLog(
        `[下拉词] 任务启动，共 ${effectiveDropdownKeywords.length} 个关键词: ${effectiveDropdownKeywords.join(", ")}`
      );
      await dataApi.startDownload({
        task_type: dropdownTaskType,
        dropdown_keywords: effectiveDropdownKeywords.join(","),
      });
      toast.success("下拉词下载任务已启动");
      refreshStatus(dropdownTaskType);
    } catch (e: any) {
      setDropdownRunning(false);
      toast.error(e.message || "启动下拉词任务失败");
    }
  };

  const handleDropdownStop = async () => {
    try {
      await dataApi.stopDownload(dropdownTaskType);
      toast.info("下拉词任务已停止");
      refreshStatus(dropdownTaskType);
      setDropdownRunning(false);
    } catch (e: any) {
      toast.error(e.message || "停止失败");
    }
  };

  const handleDeleteSelectedKeywords = async () => {
    try {
      if (selectedKeywords.length === 0) {
        toast.info("请先在整合后关键词表中选中要删除的关键词");
        return;
      }
      const res = await dataApi.deleteIndustryKeywordRows(selectedKeywords, outputFile || undefined);
      const payload = res?.data ?? res;
      const data = payload?.data ?? payload;
      toast.success(`已删除 ${Number(data?.deleted || 0)} 条关键词`);
      setSelectedKeywords([]);
      await refreshTable();
    } catch (e: any) {
      toast.error(e?.message || "删除失败");
    }
  };

  const handleDeleteSelectedDropdownRows = async () => {
    try {
      const targets = filteredDropdownRows.filter((row: any) => selectedDropdownRowKeySet.has(getDropdownRowKey(row)));
      if (targets.length === 0) {
        toast.info("请先在下拉词内容表中选中要删除的关键词");
        return;
      }
      const rows = targets.map((r: any) => ({
        源关键词: String(r?.["源关键词"] ?? ""),
        原词: String(r?.["原词"] ?? ""),
        下拉词: String(r?.["下拉词"] ?? ""),
      }));
      const res = await dataApi.deleteIndustryKeywordDropdownRows(rows, dropdownOutputFile || undefined);
      const payload = res?.data ?? res;
      const data = payload?.data ?? payload;
      toast.success(`已删除 ${Number(data?.deleted || 0)} 条下拉词`);
      setSelectedDropdownRowKeys([]);
      await refreshDropdownTable();
    } catch (e: any) {
      toast.error(e?.message || "删除失败");
    }
  };

  const openTitleDialog = () => {
    setTitleDialogOpen(true);
    setTitleResultContent("");
    setTitleResultRows([]);
    setTitleResultFile("");
    setTitleSelectedKeywords([]);
    setTitleSelectedSourcePools(activeSourcePools);
    setTitleRunMessage("");
    setTitleRunError("");
    titleResultPageRef.current = 1;
    setTitleResultPage(1);
    void (async () => {
      await refreshTitleStatus();
      await refreshTitleResult(1);
    })();
  };

  const toggleSelectTitleKeyword = (kw: string) => {
    const v = String(kw || "").trim();
    if (!v) return;
    setTitleSelectedKeywords((prev) => (prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v]));
  };

  const toggleTitleSourcePool = (source: string) => {
    const value = String(source || "").trim();
    if (!value) return;
    setTitleSelectedSourcePools((prev) =>
      prev.includes(value) ? prev.filter((item) => item !== value) : [...prev, value]
    );
    setTitleSelectedKeywords([]);
  };

  const stopTitlePoll = () => {
    if (titlePollRef.current !== null) {
      window.clearInterval(titlePollRef.current);
      titlePollRef.current = null;
    }
  };

  const refreshTitleStatus = async () => {
    try {
      const res = await dataApi.getIndustryKeywordTitleGenerateStatus();
      const payload = res?.data || res;
      const status = payload?.data || payload;
      const persistent = status?.persistent_progress || {};
      const s = String(status?.status || "idle");
      const completedScenes = Number(persistent?.completed_scenes ?? status?.progress ?? 0);
      const totalScenes = Number(persistent?.total_scenes ?? status?.total ?? 0);
      const generatedTitles = Number(persistent?.generated_titles ?? 0);
      const totalTitles = Number(persistent?.total_titles ?? 0);
      const canResume = Boolean(persistent?.can_resume);
      setTitleCanResume(canResume);
      setTitleProgress({ completedScenes, totalScenes, generatedTitles, totalTitles });

      const progressText = totalScenes > 0
        ? `已完成 ${completedScenes}/${totalScenes} 个场景，已生成 ${generatedTitles}/${totalTitles} 条标题`
        : "";
      const msg =
        s === "running"
          ? `运行中${status?.current_step ? `｜${status.current_step}` : progressText ? `｜${progressText}` : ""}`
          : s === "stopping"
            ? "正在停止"
            : s === "completed"
              ? `已完成${progressText ? `｜${progressText}` : ""}`
              : s === "failed"
                ? `已失败${status?.error ? `｜${status.error}` : ""}${canResume ? "｜可从断点继续" : ""}`
                : canResume
                  ? `检测到未完成任务｜${progressText}｜可从断点继续`
                  : persistent?.exists && progressText
                    ? `上次任务${persistent?.status === "completed" ? "已完成" : "已保存"}｜${progressText}`
                    : "空闲";
      setTitleRunMessage(msg);
      setTitleRunError(s === "failed" ? String(status?.error || persistent?.last_error || "任务执行失败") : "");
      return s;
    } catch (e: any) {
      setTitleRunMessage("");
      setTitleRunError(e?.message || "获取状态失败");
      return "idle";
    }
  };

  const refreshTitleResult = async (page: number = titleResultPageRef.current) => {
    const targetPage = Math.max(1, page);
    const res = await dataApi.getIndustryKeywordTitleGenerateResultPaged(targetPage, 20);
    const payload = res?.data || res;
    const data = payload?.data || payload;
    let result = data?.result ?? data;

    // 兼容服务刚升级、检查点为空但内存任务仍保有结果的情况：分页结果为空时
    // 再读取一次完整结果接口，并在前端切成当前页，避免“任务完成但列表不显示”。
    const pagedRows = Array.isArray(result?.rows) ? result.rows : [];
    if (!result || pagedRows.length === 0) {
      try {
        const legacyRes = await dataApi.getIndustryKeywordTitleGenerateResult();
        const legacyPayload = legacyRes?.data || legacyRes;
        const legacyData = legacyPayload?.data || legacyPayload;
        const legacyResult = legacyData?.result ?? legacyData;
        const allRows = Array.isArray(legacyResult?.rows) ? legacyResult.rows : [];
        if (legacyResult && allRows.length > 0) {
          const total = allRows.length;
          const totalPages = Math.max(1, Math.ceil(total / 20));
          const responsePage = Math.min(targetPage, totalPages);
          const start = (responsePage - 1) * 20;
          result = {
            ...legacyResult,
            content: "",
            rows: allRows.slice(start, start + 20),
            pagination: { page: responsePage, page_size: 20, total, total_pages: totalPages },
          };
        }
      } catch {
        // 保留分页接口原始结果，由下面的空结果分支统一处理。
      }
    }

    if (!result) {
      setTitleResultRows([]);
      setTitleResultTotal(0);
      setTitleResultTotalPages(1);
      return null;
    }
    const pagination = result?.pagination || {};
    const resultRows = Array.isArray(result?.rows) ? result.rows : [];
    const responsePage = Math.max(1, Number(pagination?.page || targetPage));
    titleResultPageRef.current = responsePage;
    setTitleResultPage(responsePage);
    setTitleResultRows(resultRows);
    setTitleResultTotal(Number(pagination?.total ?? resultRows.length));
    setTitleResultTotalPages(Math.max(1, Number(pagination?.total_pages || 1)));
    setTitleResultContent(String(result?.content || ""));
    setTitleResultFile(String(result?.title_excel_write?.file || result?.output_file || ""));
    return result;
  };

  const loadTitleResultPage = async (page: number) => {
    const targetPage = Math.min(Math.max(1, page), Math.max(1, titleResultTotalPages));
    try {
      await refreshTitleResult(targetPage);
    } catch (e: any) {
      toast.error(e?.message || "加载标题结果分页失败");
    }
  };

  const startTitlePolling = () => {
    stopTitlePoll();
    titlePollRef.current = window.setInterval(async () => {
      const s = await refreshTitleStatus();
      try {
        await refreshTitleResult(titleResultPageRef.current);
      } catch {
        // 状态轮询继续运行，下一轮自动重试分页结果读取。
      }
      if (s === "completed" || s === "failed" || s === "idle") {
        stopTitlePoll();
        setTitleGenerating(false);
        if (s === "completed") {
          const result: any = await refreshTitleResult(titleResultPageRef.current);
          const rows = Array.isArray(result?.rows) ? result.rows : [];
          const total = Number(result?.pagination?.total ?? rows.length);
          const w = result?.title_excel_write || {};
          const added = Number(w?.added || 0);
          const skipped = Number(w?.skipped || 0);
          const writeErr = String(w?.error || "");
          const excelFile = String(w?.file || "");
          const excelCreated = Boolean(w?.created);
          if (total <= 0) {
            const message = "任务已完成，但未读取到任何生成标题，请更新后端文件并重启后端后重新运行";
            setTitleRunError(message);
            toast.error(message);
          } else if (writeErr) {
            const message = `已生成 ${total} 条，但写入标题Excel失败：${writeErr}`;
            setTitleRunError(message);
            toast.error(message);
          } else if (added + skipped <= 0) {
            const message = `已生成 ${total} 条，但Excel写入统计为0${excelFile ? `｜目标：${excelFile}` : ""}`;
            setTitleRunError(message);
            toast.error(message);
          } else {
            setTitleRunError("");
            toast.success(
              `标题生成完成，共 ${total} 条；${excelCreated ? "已新建标题Excel并写入" : "已追加到标题Excel"} ${added} 条，重复 ${skipped} 条${excelFile ? `｜${excelFile}` : ""}`
            );
          }
        }
      }
    }, 1500);
  };

  // 弹窗内部步骤："subdirs"选子目录 | "scenes"选场景
  const [scenePickerStep, setScenePickerStep] = useState<"subdirs" | "scenes">("subdirs");
  // 子目录列表（第一步）
  const [subdirList, setSubdirList] = useState<string[]>([]);
  const [subdirSelected, setSubdirSelected] = useState<string[]>([]);
  // 场景列表（第二步）
  const [scenePickerExtractLoading, setScenePickerExtractLoading] = useState(false);

  const handleFetchScenesFromImageDir = async () => {
    // 第一步：加载一级子目录列表
    setScenePickerStep("subdirs");
    setScenePickerLoading(true);
    setScenePickerOpen(true);
    setSubdirSelected([]);
    setScenePickerList([]);
    setScenePickerSelected([]);
    try {
      const res: any = await uploadApi.getPrimarySubdirs();
      const data = res?.data?.data || res?.data || {};
      const subdirs: string[] = data.subdirs || [];
      if (subdirs.length === 0) {
        toast.warning("原图目录下没有子目录，请确认目录配置是否正确");
        setScenePickerOpen(false);
        return;
      }
      setSubdirList(subdirs);
    } catch (e: any) {
      toast.error(e?.message || "获取子目录失败");
      setScenePickerOpen(false);
    } finally {
      setScenePickerLoading(false);
    }
  };

  const handleSubdirConfirm = async () => {
    // 选好子目录后直接提取所有场景并填入输入框
    if (subdirSelected.length === 0) {
      toast.warning("请至少选择一个子目录");
      return;
    }
    setScenePickerExtractLoading(true);
    try {
      const res: any = await uploadApi.getScenesFromSubdirs(subdirSelected);
      const data = res?.data?.data || res?.data || {};
      const scenes: string[] = data.scenes || [];
      if (scenes.length === 0) {
        toast.warning("所选子目录中未解析到场景，请确认文件命名格式为：自由名-场景-价格.jpg");
        return;
      }
      // 直接将所有场景追加到场景输入框（自动去重）
      const existing = titleScenes.trim()
        ? titleScenes.trim().split("\n").map((s) => s.trim()).filter(Boolean)
        : [];
      const merged = Array.from(new Set([...existing, ...scenes]));
      setTitleScenes(merged.join("\n"));
      setScenePickerOpen(false);
      toast.success(`已自动添加 ${scenes.length} 个场景`);
    } catch (e: any) {
      toast.error(e?.message || "提取场景失败");
    } finally {
      setScenePickerExtractLoading(false);
    }
  };

  const handleScenePickerConfirm = () => {
    if (scenePickerSelected.length === 0) {
      toast.warning("请至少选择一个场景");
      return;
    }
    // 将选中的场景追加到输入框（不覆盖已有内容，自动去重）
    const existing = titleScenes.trim()
      ? titleScenes.trim().split("\n").map((s) => s.trim()).filter(Boolean)
      : [];
    const merged = Array.from(new Set([...existing, ...scenePickerSelected]));
    setTitleScenes(merged.join("\n"));
    setScenePickerOpen(false);
    toast.success(`已添加 ${scenePickerSelected.length} 个场景`);
  };

  const handleResumeTitles = async () => {
    try {
      stopTitlePoll();
      setTitleGenerating(true);
      setTitleRunError("");
      setTitleRunMessage("正在恢复上次任务...");
      await dataApi.resumeIndustryKeywordTitleGenerate();
      toast.success("已从上次断点恢复标题生成任务");
      await refreshTitleStatus();
      await refreshTitleResult(titleResultPageRef.current);
      startTitlePolling();
    } catch (e: any) {
      setTitleGenerating(false);
      stopTitlePoll();
      toast.error(e?.message || "恢复标题生成任务失败");
    }
  };

  const handleGenerateTitles = async () => {
    try {
      if (!titleScenes.trim()) {
        toast.error("请先输入场景（每行一个）");
        return;
      }
      if (titleSelectedSourcePools.length === 0) {
        toast.error("请至少选择一个源关键词池");
        return;
      }
      const minHeat = Number(titleMinKeywordHeat);
      if (!Number.isFinite(minHeat) || minHeat < 0) {
        toast.error("最低关键词热度必须是大于等于 0 的数字");
        return;
      }
      if (activeTitleKeywords.length === 0) {
        toast.error(`所选关键词池中没有热度大于等于 ${minHeat} 的关键词`);
        return;
      }
      const parsedCount = Number(titleCountPerScene);
      if (!Number.isFinite(parsedCount) || parsedCount <= 0) {
        toast.error("请填写有效的“每个场景生成数量”");
        return;
      }

      const sceneList = Array.from(new Set(
        titleScenes.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)
      ));
      const expectedTitles = sceneList.length * parsedCount;
      const scenesPerBatch = Math.max(1, Math.floor(20 / parsedCount));
      const estimatedBatches = Math.ceil(sceneList.length / scenesPerBatch);
      if (expectedTitles >= 100) {
        const confirmed = window.confirm(
          `即将启动大规模标题生成任务：\n\n` +
          `场景数：${sceneList.length}\n` +
          `每个场景：${parsedCount} 条\n` +
          `预计标题总数：${expectedTitles} 条\n` +
          `预计基础请求批次：${estimatedBatches} 批（缺失补充请求不计入）\n\n` +
          `系统会逐场景写入Excel并保存断点。确认开始吗？`
        );
        if (!confirmed) return;
      }

      stopTitlePoll();
      setTitleGenerating(true);
      setTitleRunError("");
      setTitleRunMessage("启动中...");
      titleResultPageRef.current = 1;
      setTitleResultPage(1);
      setTitleResultRows([]);
      setTitleResultTotal(0);
      setTitleResultTotalPages(1);

      const keywordsToUse = titleSelectedKeywords.length > 0 ? titleSelectedKeywords : activeTitleKeywords;
      await dataApi.startIndustryKeywordTitleGenerate({
        mode: titleMode,
        scenes: titleScenes,
        material: titleMaterial.trim() || undefined,
        titles_per_scene: parsedCount,
        keywords: keywordsToUse,
        selected_source_pools: titleSelectedSourcePools,
        min_keyword_heat: minHeat,
        output_file: outputFile || undefined,
        dropdown_output_file: dropdownOutputFile || undefined,
        resume: false,
      });
      toast.success(`标题生成任务已启动：预计 ${expectedTitles} 条，约 ${estimatedBatches} 个基础批次`);

      await refreshTitleStatus();
      await refreshTitleResult(1);
      startTitlePolling();
    } catch (e: any) {
      setTitleGenerating(false);
      stopTitlePoll();
      toast.error(e?.message || "启动生成标题失败");
    }
  };

  useEffect(() => {
    return () => stopTitlePoll();
  }, []);

  useEffect(() => {
    loadConfig();
    refreshStatus(taskType);
    refreshStatus(dropdownTaskType);
    refreshTable();
    refreshDropdownTable();
  }, []);

  useEffect(() => {
    if (!dropdownOutputFile) return;
    refreshDropdownTable();
  }, [dropdownOutputFile]);

  useEffect(() => {
    const timer = setInterval(() => {
      const isVisible = typeof document === "undefined" ? true : document.visibilityState === "visible";
      if (!isVisible && !isRunning && !dropdownRunning) return;
      refreshStatus(taskType).then((status) => {
        if (!status) return;
        // WebSocket 连不上时，使用状态轮询作为日志兜底
        if (!wsConnectedRef.current) {
          const raw = `${status?.status || ""}|${status?.current_step || ""}|${status?.error || ""}`;
          if (raw && raw !== lastMainStatusLogRef.current) {
            lastMainStatusLogRef.current = raw;
            appendRuntimeLog(buildTaskStatusLog(status, "主任务"));
          }
        }
      });
      refreshStatus(dropdownTaskType).then((status) => {
        if (!status || wsConnectedRef.current) return;
        const step = String(status?.current_step || "");
        if (!step.includes("下拉词")) return;
        const progress = Number(status?.progress || 0);
        const terminal = status?.status === "completed" || status?.status === "failed";
        if (progress > lastDropdownProgressRef.current) {
          lastDropdownProgressRef.current = progress;
          appendRuntimeLog(buildTaskStatusLog(status, "下拉词"));
          return;
        }
        const raw = `${status?.status || ""}|${step}|${status?.error || ""}`;
        if (terminal && raw && raw !== lastDropdownStatusLogRef.current) {
          lastDropdownStatusLogRef.current = raw;
          appendRuntimeLog(buildTaskStatusLog(status, "下拉词"));
        }
      });
      if (!isRunning && !dropdownRunning) {
        return;
      }
    }, isRunning || dropdownRunning ? 2000 : 30000);
    return () => clearInterval(timer);
  }, [isRunning, dropdownRunning]);

  useEffect(() => {
    const ws = createLogSocket((data) => {
      wsConnectedRef.current = true;
      const payload = data?.data || data;
      const moduleName = String(payload?.module || "");
      const msg = payload?.message || payload?.msg || payload?.text;
      if (!msg) return;
      if (moduleName && moduleName !== "data_download") return;
      const text = String(msg);
      if (!text.includes("行业关键词") && !text.includes("下拉词")) return;
      setLogs((prev) => [...prev, String(msg)].slice(-500));
    });
    if (ws) {
      ws.onopen = () => {
        wsConnectedRef.current = true;
      };
      ws.onerror = () => {
        wsConnectedRef.current = false;
      };
      ws.onclose = () => {
        wsConnectedRef.current = false;
      };
    } else {
      wsConnectedRef.current = false;
    }
    return () => {
      try {
        ws?.close();
      } catch {
        // ignore
      }
    };
  }, []);

  return (
    <div className="p-8">
      <div className="mb-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>数据下载</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">行业关键词</span>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">行业关键词</h1>
            <p className="text-sm text-muted-foreground mt-1">
              按行业大词批量下载关键词数据，下载完成后自动执行关键词整合
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span className={isRunning ? "text-primary" : ""}>主任务：{isRunning ? "运行中" : "待启动"}</span>
            <span>·</span>
            <span className={dropdownRunning ? "text-primary" : ""}>下拉词：{dropdownRunning ? "运行中" : "待启动"}</span>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2 space-y-6">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">整合后关键词</CardTitle>
                <div className="flex items-center gap-2">
                  <Button size="sm" variant="destructive" onClick={handleDeleteSelectedKeywords}>
                    删除选中
                  </Button>
                  <Button size="sm" variant="outline" className="gap-1.5" onClick={refreshTable}>
                    <RefreshCw className="w-3.5 h-3.5" />
                    刷新
                  </Button>
                </div>
              </div>
              <div className="text-xs text-muted-foreground">
                当前排序列：{latestCol || "无"}（降序）
              </div>
              <div className="text-xs text-muted-foreground">
                展示规则：最新值 &gt; 40，或最近5次中至少3次 &gt; 40（当前 {filteredRows.length} 条）
              </div>
              <div className="text-xs text-muted-foreground">
                点击行可选择关键词用于“下拉词下载”（已选 {selectedKeywords.length} 条，绿色高亮）
              </div>
              <Input
                value={tableQuery}
                onChange={(e) => setTableQuery(e.target.value)}
                placeholder="搜索整合后关键词（包含匹配）"
                className="h-8 text-xs"
              />
            </CardHeader>
            <CardContent>
              <div className="h-[560px] overflow-auto rounded-lg border border-border/50">
                <table className="w-full text-sm table-fixed">
                  <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                    <tr className="border-b">
                      {(table.columns || []).length === 0 ? (
                        <th className="text-left py-3 px-3 font-medium text-xs text-muted-foreground">暂无列</th>
                      ) : (
                        (table.columns || []).map((c: string) => (
                          <th
                            key={c}
                            className={`text-left py-3 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap ${
                              c === "关键词" ? "w-[200px]" : "min-w-[110px]"
                            }`}
                          >
                            {c}
                          </th>
                        ))
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {filteredKeywordRows.length === 0 ? (
                      <tr>
                        <td colSpan={Math.max((table.columns || []).length, 1)} className="py-6 text-center text-xs text-muted-foreground">
                          暂无符合条件的数据（最新值&gt;40 或 最近5次中至少3次&gt;40）
                        </td>
                      </tr>
                    ) : (
                      filteredKeywordRows.map((row: any, i: number) => {
                        const kw = String(row?.["关键词"] || "").trim();
                        const selected = kw ? selectedKeywordSet.has(kw) : false;
                        return (
                        <tr
                          key={i}
                          className={`border-b last:border-0 cursor-pointer ${selected ? "bg-emerald-100/70 hover:bg-emerald-100/90" : "hover:bg-accent/30"}`}
                          onClick={() => toggleSelectKeyword(row)}
                        >
                          {(table.columns || []).map((c: string) => (
                            <td
                              key={c}
                              className={`py-2.5 px-3 text-xs whitespace-nowrap ${
                                c === "关键词" ? "w-[200px]" : "min-w-[110px]"
                              }`}
                            >
                              {c === "关键词" ? (
                                <div className="truncate" title={String(row?.[c] ?? "")}>
                                  {String(row?.[c] ?? "")}
                                </div>
                              ) : (
                                String(row?.[c] ?? "")
                              )}
                            </td>
                          ))}
                        </tr>
                      )})
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">下拉词内容</CardTitle>
                <div className="flex items-center gap-2">
                  <Button size="sm" variant="destructive" onClick={handleDeleteSelectedDropdownRows}>
                    删除选中
                  </Button>
                  <Button size="sm" variant="outline" className="gap-1.5" onClick={refreshDropdownTable}>
                    <RefreshCw className="w-3.5 h-3.5" />
                    刷新
                  </Button>
                </div>
              </div>
              <div className="text-xs text-muted-foreground">
                来源文件：{dropdownTable?.file || dropdownOutputFile || "未配置"}
              </div>
              <Input
                value={dropdownQuery}
                onChange={(e) => setDropdownQuery(e.target.value)}
                placeholder="搜索下拉词内容（包含匹配）"
                className="h-8 text-xs"
              />
            </CardHeader>
            <CardContent>
              <div className="h-[440px] overflow-auto rounded-lg border border-border/50">
                <table className="w-full text-sm table-fixed">
                  <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                    <tr className="border-b">
                      <th className="text-left py-3 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap min-w-[150px]">源关键词池</th>
                      <th className="text-left py-3 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap min-w-[160px]">原词</th>
                      <th className="text-left py-3 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap w-[100px]">关键词热度</th>
                      <th className="text-left py-3 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap min-w-[220px]">下拉词</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredDropdownRows.length === 0 ? (
                      <tr>
                        <td
                          colSpan={4}
                          className="py-6 text-center text-xs text-muted-foreground"
                        >
                          暂无下拉词结果（先执行“下载下拉词”）
                        </td>
                      </tr>
                    ) : (
                      filteredDropdownRows.map((row: any, i: number) => {
                        const rowKey = getDropdownRowKey(row);
                        const selected = selectedDropdownRowKeySet.has(rowKey);
                        return (
                        <tr
                          key={i}
                          className={`border-b last:border-0 cursor-pointer ${selected ? "bg-emerald-100/70 hover:bg-emerald-100/90" : "hover:bg-accent/30"}`}
                          onClick={() => toggleSelectDropdownRow(row)}
                        >
                          <td className="py-2.5 px-3 text-xs whitespace-nowrap">
                            <div className="truncate" title={String(row?.["源关键词"] ?? "")}>
                              {String(row?.["源关键词"] ?? "")}
                            </div>
                          </td>
                          <td className="py-2.5 px-3 text-xs whitespace-nowrap">
                            <div className="truncate" title={String(row?.["原词"] ?? "")}>
                              {String(row?.["原词"] ?? "")}
                            </div>
                          </td>
                          <td className="py-2.5 px-3 text-xs tabular-nums">
                            {parseKeywordHeat(row?.["关键词热度"])}
                          </td>
                          <td className="py-2.5 px-3 text-xs whitespace-nowrap">
                            <div className="truncate" title={String(row?.["下拉词"] ?? "")}>
                              {String(row?.["下拉词"] ?? "")}
                            </div>
                          </td>
                        </tr>
                      )})
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">配置区域</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">保存目录</Label>
                <Input value={saveFolder} onChange={(e) => setSaveFolder(e.target.value)} className="text-xs font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">整合输出文件</Label>
                <Input value={outputFile} onChange={(e) => setOutputFile(e.target.value)} className="text-xs font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">下拉词存放路径（Excel）</Label>
                <Input value={dropdownOutputFile} onChange={(e) => setDropdownOutputFile(e.target.value)} className="text-xs font-mono" />
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={saveConfig}>保存配置</Button>
                <Button size="sm" variant="ghost" onClick={loadConfig}>重载</Button>
                <Button size="sm" variant="default" className="gap-1.5" onClick={openTitleDialog}>
                  <Wand2 className="w-3.5 h-3.5" />
                  生成标题
                </Button>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">行业关键词大词（需手动填写行业关键词，逗号/换行分隔）</Label>
                <textarea
                  value={bigKeywords}
                  onChange={(e) => setBigKeywords(e.target.value)}
                  rows={7}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-xs font-mono"
                  placeholder="tiny house,container house,prefab house"
                />
                <div className="pt-1">
                  <Button size="sm" onClick={isRunning ? handleStop : handleStart} variant={isRunning ? "destructive" : "default"} className="gap-1.5">
                    {isRunning ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                    {isRunning ? "停止主任务" : "开始执行"}
                  </Button>
                </div>
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">下拉词关键词（可填入关键词，也可从左侧整合后关键词表中选中）</Label>
                <textarea
                  value={dropdownKeywords}
                  onChange={(e) => setDropdownKeywords(e.target.value)}
                  rows={4}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-xs font-mono"
                  placeholder="tiny house kits, prefab house"
                />
                <div className="text-[11px] text-muted-foreground">
                  当前生效关键词：{effectiveDropdownKeywords.length} 个（手工配置 + 左侧绿色选中，自动去重）
                </div>
                <div className="pt-1">
                  <Button
                    size="sm"
                    onClick={dropdownRunning ? handleDropdownStop : handleDropdownStart}
                    variant={dropdownRunning ? "destructive" : "default"}
                    className="gap-1.5"
                  >
                    {dropdownRunning ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                    {dropdownRunning ? "停止下拉词" : "下载下拉词"}
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">运行日志</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-56 overflow-y-auto rounded-lg bg-gray-950 p-3">
                <div className="space-y-1 font-mono text-xs">
                  {logs.map((log, i) => (
                    <div key={i} className="text-gray-300">{log}</div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      <Dialog open={titleDialogOpen} onOpenChange={setTitleDialogOpen}>
        <DialogContent className="w-[66vw] max-w-[1050px] sm:max-w-[1050px] h-[80vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle>生成标题</DialogTitle>
          </DialogHeader>
          <div className="flex-1 min-h-0 overflow-y-auto pr-2 space-y-3">
            <div className="flex items-center gap-2">
              <Button size="sm" variant={titleMode === "industry_hot" ? "default" : "outline"} onClick={() => setTitleMode("industry_hot")}>
                行业热词生成标题
              </Button>
              <Button size="sm" variant={titleMode === "dropdown" ? "default" : "outline"} onClick={() => setTitleMode("dropdown")}>
                下拉词生成
              </Button>
              <Badge variant="secondary">
                已选词池 {titleSelectedSourcePools.length} / {activeSourcePools.length}｜符合热度 {activeTitleKeywords.length} 个词
              </Badge>
            </div>

            <div className="grid grid-cols-3 gap-4 items-start">
              <div className="col-span-1 space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label className="text-xs text-muted-foreground">场景（每行一个）</Label>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-6 text-xs px-2"
                    onClick={handleFetchScenesFromImageDir}
                  >
                    从原图目录获取
                  </Button>
                </div>
                <Textarea
                  value={titleScenes}
                  onChange={(e) => setTitleScenes(e.target.value)}
                  rows={3}
                  className="text-xs"
                  placeholder="例如：庭院办公室&#10;露营民宿&#10;工地宿舍"
                />
              </div>
              <div className="col-span-1 space-y-1.5">
                <Label className="text-xs text-muted-foreground">材质（每行一个，可选）</Label>
                <Textarea
                  value={titleMaterial}
                  onChange={(e) => setTitleMaterial(e.target.value)}
                  rows={3}
                  className="text-xs"
                  placeholder="例如：&#10;EPS Sandwich Panel&#10;Rock Wool&#10;PU Sandwich Panel"
                />
              </div>
              <div className="col-span-1 space-y-1.5">
                <Label className="text-xs text-muted-foreground">每个场景生成数量</Label>
                <Input
                  type="number"
                  min={1}
                  max={50}
                  value={titleCountPerScene}
                  onChange={(e) => setTitleCountPerScene(e.target.value)}
                  className="text-xs"
                />
              </div>
            </div>

            <div className="rounded-md border border-border/50 p-3 space-y-3">
              <div className="grid grid-cols-[minmax(0,1fr)_220px] gap-4 items-start">
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <Label className="text-xs text-muted-foreground">源关键词池（可多选）</Label>
                    <div className="flex items-center gap-1">
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-6 px-2 text-xs"
                        onClick={() => {
                          setTitleSelectedSourcePools(activeSourcePools);
                          setTitleSelectedKeywords([]);
                        }}
                      >
                        全选
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-6 px-2 text-xs"
                        onClick={() => {
                          setTitleSelectedSourcePools([]);
                          setTitleSelectedKeywords([]);
                        }}
                      >
                        清空
                      </Button>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2 max-h-24 overflow-y-auto">
                    {activeSourcePools.length === 0 ? (
                      <span className="text-xs text-muted-foreground">暂无源关键词池，请先重新下载并整合关键词</span>
                    ) : (
                      activeSourcePools.map((source) => {
                        const selected = titleSelectedSourcePoolSet.has(source);
                        return (
                          <Button
                            key={source}
                            type="button"
                            size="sm"
                            variant={selected ? "default" : "outline"}
                            className="h-7 text-xs"
                            onClick={() => toggleTitleSourcePool(source)}
                          >
                            {source}
                          </Button>
                        );
                      })
                    )}
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">最低关键词热度（≥）</Label>
                  <Input
                    type="number"
                    min={0}
                    step={1}
                    value={titleMinKeywordHeat}
                    onChange={(e) => setTitleMinKeywordHeat(e.target.value)}
                    className="text-xs"
                  />
                  <div className="text-[11px] text-muted-foreground">
                    只把所选词池中达到该热度的关键词提交给大模型
                  </div>
                </div>
              </div>
              <div className="text-xs text-muted-foreground">
                当前筛选：{titleSelectedSourcePools.length} 个词池，符合条件 {activeTitleKeywords.length} 个关键词
                {titleSelectedKeywords.length > 0 ? `，其中手工选中 ${titleSelectedKeywords.length} 个` : "，未手工选词时默认提交全部符合条件的关键词"}
              </div>
            </div>

            <div className="rounded-md border border-border/50">
              <div className="px-3 py-2 text-xs text-muted-foreground border-b">
                {titleMode === "industry_hot" ? "行业热词关键词表（已按词池和热度筛选）" : "下拉词关键词表（已按词池和原词热度筛选）"}
              </div>
              <div className="max-h-56 overflow-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-muted/80">
                    <tr className="border-b">
                      <th className="text-left py-2 px-3 font-medium w-[240px]">源关键词池</th>
                      <th className="text-left py-2 px-3 font-medium w-[110px]">热度</th>
                      <th className="text-left py-2 px-3 font-medium">关键词</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeTitleKeywordDetails.length === 0 ? (
                      <tr>
                        <td colSpan={3} className="py-4 px-3 text-muted-foreground">
                          暂无符合所选词池和最低热度条件的关键词
                        </td>
                      </tr>
                    ) : (
                      activeTitleKeywordDetails.map((detail) => {
                        const selected = titleSelectedSet.has(detail.keyword);
                        return (
                        <tr
                          key={detail.keyword}
                          className={`border-b last:border-0 cursor-pointer ${selected ? "bg-emerald-100/70 hover:bg-emerald-100/90" : "hover:bg-accent/30"}`}
                          onClick={() => toggleSelectTitleKeyword(detail.keyword)}
                        >
                          <td className="py-1.5 px-3">
                            <div className="truncate" title={detail.sources.join("、")}>{detail.sources.join("、")}</div>
                          </td>
                          <td className="py-1.5 px-3 tabular-nums">{detail.heat}</td>
                          <td className="py-1.5 px-3">{detail.keyword}</td>
                        </tr>
                      )})
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" onClick={handleGenerateTitles} disabled={titleGenerating}>
                  {titleGenerating ? "生成中..." : "运行新任务"}
                </Button>
                {titleCanResume ? (
                  <Button size="sm" variant="outline" onClick={handleResumeTitles} disabled={titleGenerating}>
                    继续上次任务
                  </Button>
                ) : null}
                {titleResultFile ? <span className="text-xs text-muted-foreground">标题Excel：{titleResultFile}</span> : null}
              </div>
              {titleProgress.totalScenes > 0 ? (
                <div className="rounded-md border border-border/50 bg-muted/20 px-3 py-2 text-xs">
                  <span className="font-medium">任务进度：</span>
                  已完成 {titleProgress.completedScenes}/{titleProgress.totalScenes} 个场景，
                  已生成 {titleProgress.generatedTitles}/{titleProgress.totalTitles} 条标题
                </div>
              ) : null}
              {titleRunMessage ? <div className="text-xs text-muted-foreground">{titleRunMessage}</div> : null}
              {titleRunError ? <div className="text-xs text-destructive">{titleRunError}</div> : null}
            </div>

            {titleResultRows.length > 0 ? (
              <div className="rounded-md border border-border/50">
                <div className="flex items-center justify-between gap-2 px-3 py-2 text-xs text-muted-foreground border-b">
                  <span>生成结果（场景，标题）</span>
                  <span>共 {titleResultTotal} 条｜第 {titleResultPage}/{titleResultTotalPages} 页｜每页 20 条</span>
                </div>
                <div className="max-h-56 overflow-auto">
                  <table className="w-full text-xs">
                    <thead className="sticky top-0 bg-muted/80">
                      <tr className="border-b">
                        <th className="text-left py-2 px-3 font-medium w-[180px]">场景</th>
                        <th className="text-left py-2 px-3 font-medium">标题</th>
                      </tr>
                    </thead>
                    <tbody>
                      {titleResultRows.map((r, i) => (
                        <tr key={`${r.scene}-${i}`} className="border-b last:border-0">
                          <td className="py-1.5 px-3 whitespace-nowrap">{r.scene}</td>
                          <td className="py-1.5 px-3">{r.title}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {titleResultTotalPages > 1 ? (
                  <div className="border-t px-3 py-2">
                    <Pagination>
                      <PaginationContent>
                        <PaginationItem>
                          <PaginationPrevious
                            href="#"
                            className={titleResultPage <= 1 ? "pointer-events-none opacity-50" : ""}
                            onClick={(event) => {
                              event.preventDefault();
                              if (titleResultPage > 1) void loadTitleResultPage(titleResultPage - 1);
                            }}
                          />
                        </PaginationItem>
                        {titleResultPage > 3 ? (
                          <>
                            <PaginationItem>
                              <PaginationLink
                                href="#"
                                onClick={(event) => {
                                  event.preventDefault();
                                  void loadTitleResultPage(1);
                                }}
                              >
                                1
                              </PaginationLink>
                            </PaginationItem>
                            {titleResultPage > 4 ? (
                              <PaginationItem><PaginationEllipsis /></PaginationItem>
                            ) : null}
                          </>
                        ) : null}
                        {Array.from(
                          { length: Math.min(5, titleResultTotalPages) },
                          (_, index) => Math.max(
                            1,
                            Math.min(titleResultPage - 2, titleResultTotalPages - 4)
                          ) + index
                        ).map((page) => (
                          <PaginationItem key={page}>
                            <PaginationLink
                              href="#"
                              isActive={page === titleResultPage}
                              onClick={(event) => {
                                event.preventDefault();
                                void loadTitleResultPage(page);
                              }}
                            >
                              {page}
                            </PaginationLink>
                          </PaginationItem>
                        ))}
                        {titleResultPage < titleResultTotalPages - 2 ? (
                          <>
                            {titleResultPage < titleResultTotalPages - 3 ? (
                              <PaginationItem><PaginationEllipsis /></PaginationItem>
                            ) : null}
                            <PaginationItem>
                              <PaginationLink
                                href="#"
                                onClick={(event) => {
                                  event.preventDefault();
                                  void loadTitleResultPage(titleResultTotalPages);
                                }}
                              >
                                {titleResultTotalPages}
                              </PaginationLink>
                            </PaginationItem>
                          </>
                        ) : null}
                        <PaginationItem>
                          <PaginationNext
                            href="#"
                            className={titleResultPage >= titleResultTotalPages ? "pointer-events-none opacity-50" : ""}
                            onClick={(event) => {
                              event.preventDefault();
                              if (titleResultPage < titleResultTotalPages) void loadTitleResultPage(titleResultPage + 1);
                            }}
                          />
                        </PaginationItem>
                      </PaginationContent>
                    </Pagination>
                  </div>
                ) : null}
              </div>
            ) : null}

            {titleResultContent ? (
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">原始返回</Label>
                <Textarea value={titleResultContent} readOnly rows={8} className="text-xs font-mono" />
              </div>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>

      {/* 原图目录场景提取弹窗 */}
      <Dialog open={scenePickerOpen} onOpenChange={setScenePickerOpen}>
        <DialogContent className="w-[480px] max-w-[95vw] max-h-[75vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>选择子目录（自动提取场景）</DialogTitle>
          </DialogHeader>

          <div className="flex-1 min-h-0 overflow-y-auto">
            {scenePickerLoading ? (
              <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">加载中...</div>
            ) : subdirList.length === 0 ? (
              <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">未找到子目录</div>
            ) : (
              <div className="space-y-1 p-1">
                {subdirList.map((dir) => {
                  const checked = subdirSelected.includes(dir);
                  return (
                    <div
                      key={dir}
                      className={`flex items-center gap-3 px-3 py-2 rounded-md cursor-pointer hover:bg-accent transition-colors ${
                        checked ? "bg-accent" : ""
                      }`}
                      onClick={() =>
                        setSubdirSelected((prev) =>
                          prev.includes(dir) ? prev.filter((x) => x !== dir) : [...prev, dir]
                        )
                      }
                    >
                      <input
                        type="checkbox"
                        readOnly
                        checked={checked}
                        className="w-4 h-4 accent-primary pointer-events-none"
                      />
                      <span className="flex-1 text-sm font-medium">{dir}</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
          <div className="flex items-center justify-between pt-3 border-t gap-2">
            <div className="flex gap-2">
              <Button size="sm" variant="outline" className="text-xs"
                onClick={() => setSubdirSelected(subdirList)}>全选</Button>
              <Button size="sm" variant="outline" className="text-xs"
                onClick={() => setSubdirSelected([])}>清空</Button>
            </div>
            <span className="text-xs text-muted-foreground">已选 {subdirSelected.length} / {subdirList.length} 个子目录</span>
            <Button
              size="sm"
              onClick={handleSubdirConfirm}
              disabled={subdirSelected.length === 0 || scenePickerExtractLoading}
            >
              {scenePickerExtractLoading ? "提取中..." : "确认提取"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

