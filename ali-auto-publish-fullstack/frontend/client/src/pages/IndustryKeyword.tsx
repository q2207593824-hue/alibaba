import { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { ChevronRight, Pause, Play, RefreshCw, Wand2 } from "lucide-react";
import { configApi, createLogSocket, dataApi } from "@/lib/api";
import { configApi, createLogSocket, dataApi, imageApi } from "@/lib/api";

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
  const [titleRunMessage, setTitleRunMessage] = useState("");
  const [titleRunError, setTitleRunError] = useState("");
  const titlePollRef = useRef<number | null>(null);

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

    const metricCols = columns.filter((c: string) => c !== "关键词");
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
        return { 原词: origin, 下拉词: suggestion };
      })
      .filter((row: any) => row.原词 || row.下拉词);
  }, [dropdownTable]);
  const filteredDropdownRows = useMemo(() => {
    const q = dropdownQuery.trim().toLowerCase();
    if (!q) return dropdownRows;
    return dropdownRows.filter((row: any) => {
      const a = String(row?.["原词"] ?? "").toLowerCase();
      const b = String(row?.["下拉词"] ?? "").toLowerCase();
      return a.includes(q) || b.includes(q);
    });
  }, [dropdownRows, dropdownQuery]);
  const industryTitleKeywords = useMemo<string[]>(
    () =>
      Array.from(
        new Set<string>(
          filteredKeywordRows
            .map((r: any) => String(r?.["关键词"] ?? "").trim())
            .filter((x: string) => Boolean(x))
        )
      ),
    [filteredKeywordRows]
  );
  const dropdownTitleKeywords = useMemo<string[]>(
    () =>
      Array.from(
        new Set<string>(
          filteredDropdownRows
            .map((r: any) => String(r?.["下拉词"] ?? "").trim())
            .filter((x: string) => Boolean(x))
        )
      ),
    [filteredDropdownRows]
  );
  const activeTitleKeywords = titleMode === "industry_hot" ? industryTitleKeywords : dropdownTitleKeywords;
  const titleSelectedSet = useMemo(() => new Set(titleSelectedKeywords), [titleSelectedKeywords]);

  useEffect(() => {
    // 模式切换或表数据刷新时：清理掉不存在的已选关键词
    setTitleSelectedKeywords((prev) => prev.filter((kw) => activeTitleKeywords.includes(kw)));
  }, [titleMode, activeTitleKeywords]);

  const toggleSelectKeyword = (row: any) => {
    const kw = String(row?.["关键词"] || "").trim();
    if (!kw) return;
    setSelectedKeywords((prev) => {
      const exists = prev.includes(kw);
      if (exists) return prev.filter((x) => x !== kw);
      return [...prev, kw];
    });
  };
  const getDropdownRowKey = (row: any) => `${String(row?.["原词"] ?? "").trim()}__${String(row?.["下拉词"] ?? "").trim()}`;
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
      const rows = targets.map((r: any) => ({ 原词: String(r?.["原词"] ?? ""), 下拉词: String(r?.["下拉词"] ?? "") }));
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
    setTitleRunMessage("");
    setTitleRunError("");
  };

  const toggleSelectTitleKeyword = (kw: string) => {
    const v = String(kw || "").trim();
    if (!v) return;
    setTitleSelectedKeywords((prev) => (prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v]));
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
      const s = String(status?.status || "idle");
      const msg =
        s === "running"
          ? `运行中${status?.current_step ? `｜${status.current_step}` : ""}`
          : s === "stopping"
            ? "正在停止"
            : s === "completed"
              ? "已完成"
              : s === "failed"
                ? `已失败${status?.error ? `｜${status.error}` : ""}`
                : "空闲";
      setTitleRunMessage(msg);
      setTitleRunError(s === "failed" ? String(status?.error || "任务执行失败") : "");
      return s;
    } catch (e: any) {
      setTitleRunMessage("");
      setTitleRunError(e?.message || "获取状态失败");
      return "idle";
    }
  };

  const refreshTitleResult = async () => {
    const res = await dataApi.getIndustryKeywordTitleGenerateResult();
    const payload = res?.data || res;
    const data = payload?.data || payload;
    const result = data?.result ?? data;
    return result;
  };

  const handleFetchScenesFromImageDir = async () => {
    try {
      const res: any = await imageApi.getAiGenInputScenes();
      const data = res?.data?.data || res?.data || {};
      const scenes: string[] = data.scenes || [];
      const maxCount: number = data.max_count || 1;
      if (scenes.length === 0) {
        toast.warning("未从图片文件名中解析到场景，请确认文件名格式为：自由名-场景-价格");
        return;
      }
      setTitleScenes(scenes.join("\n"));
      setTitleCountPerScene(String(maxCount));
      toast.success(`已获取 ${scenes.length} 个场景，最多出现 ${maxCount} 次`);
    } catch (e: any) {
      toast.error(e?.message || "获取场景失败");
    }
  };
  
  const handleGenerateTitles = async () => {
    try {
      if (!titleScenes.trim()) {
        toast.error("请先输入场景（每行一个）");
        return;
      }
      if (activeTitleKeywords.length === 0) {
        toast.error(titleMode === "industry_hot" ? "整合后关键词为空，无法生成标题" : "下拉词为空，无法生成标题");
        return;
      }
      const parsedCount = Number(titleCountPerScene);
      if (!Number.isFinite(parsedCount) || parsedCount <= 0) {
        toast.error("请填写有效的“每个场景生成数量”");
        return;
      }

      stopTitlePoll();
      setTitleGenerating(true);
      setTitleRunError("");
      setTitleRunMessage("启动中...");

      const keywordsToUse = titleSelectedKeywords.length > 0 ? titleSelectedKeywords : activeTitleKeywords;
      await dataApi.startIndustryKeywordTitleGenerate({
        mode: titleMode,
        scenes: titleScenes,
        material: titleMaterial.trim() || undefined,
        titles_per_scene: parsedCount,
        keywords: keywordsToUse,
        output_file: outputFile || undefined,
        dropdown_output_file: dropdownOutputFile || undefined,
      });
      toast.success("标题生成任务已启动");

      await refreshTitleStatus();
      titlePollRef.current = window.setInterval(async () => {
        const s = await refreshTitleStatus();
        if (s === "completed" || s === "failed" || s === "idle") {
          stopTitlePoll();
          setTitleGenerating(false);
          if (s === "completed") {
            try {
              const result: any = await refreshTitleResult();
              setTitleResultContent(String(result?.content || ""));
              setTitleResultRows(Array.isArray(result?.rows) ? result.rows : []);
              setTitleResultFile(String(result?.output_file || ""));
              const w = result?.title_excel_write;
              const added = Number(w?.added || 0);
              const skipped = Number(w?.skipped || 0);
              const writeErr = String(w?.error || "");
              if (writeErr) toast.error(`标题已生成，但写入标题Excel失败：${writeErr}`);
              else toast.success(`标题生成完成，写入标题Excel +${added}（跳过重复 ${skipped}）`);
            } catch (e: any) {
              toast.error(e?.message || "获取生成结果失败");
            }
          }
        }
      }, 1200);
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
                      <th className="text-left py-3 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap min-w-[160px]">原词</th>
                      <th className="text-left py-3 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap min-w-[220px]">下拉词</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredDropdownRows.length === 0 ? (
                      <tr>
                        <td
                          colSpan={2}
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
                            <div className="truncate" title={String(row?.["原词"] ?? "")}>
                              {String(row?.["原词"] ?? "")}
                            </div>
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
                已选 {titleSelectedKeywords.length} / {activeTitleKeywords.length}（不选则默认全量）
              </Badge>
            </div>

            <div className="grid grid-cols-3 gap-4 items-start">
              <div className="col-span-1 space-y-1.5">
                <Label className="text-xs text-muted-foreground">场景（每行一个）</Label>
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

            <div className="rounded-md border border-border/50">
              <div className="px-3 py-2 text-xs text-muted-foreground border-b">
                {titleMode === "industry_hot" ? "行业热词关键词表（取整合后关键词列）" : "下拉词关键词表（取下拉词列）"}
              </div>
              <div className="max-h-56 overflow-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-muted/80">
                    <tr className="border-b">
                      <th className="text-left py-2 px-3 font-medium">关键词</th>
                    </tr>
                  </thead>
                  <tbody>
                    {activeTitleKeywords.length === 0 ? (
                      <tr>
                        <td className="py-4 px-3 text-muted-foreground">暂无可用关键词</td>
                      </tr>
                    ) : (
                      activeTitleKeywords.map((kw) => {
                        const selected = titleSelectedSet.has(kw);
                        return (
                        <tr
                          key={kw}
                          className={`border-b last:border-0 cursor-pointer ${selected ? "bg-emerald-100/70 hover:bg-emerald-100/90" : "hover:bg-accent/30"}`}
                          onClick={() => toggleSelectTitleKeyword(kw)}
                        >
                          <td className="py-1.5 px-3">{kw}</td>
                        </tr>
                      )})
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Button size="sm" onClick={handleGenerateTitles} disabled={titleGenerating}>
                {titleGenerating ? "生成中..." : "运行"}
              </Button>
              {titleResultFile ? <span className="text-xs text-muted-foreground">已保存：{titleResultFile}</span> : null}
              {titleRunMessage ? <span className="text-xs text-muted-foreground">{titleRunMessage}</span> : null}
              {titleRunError ? <span className="text-xs text-destructive">{titleRunError}</span> : null}
            </div>

            {titleResultRows.length > 0 ? (
              <div className="rounded-md border border-border/50">
                <div className="px-3 py-2 text-xs text-muted-foreground border-b">生成结果（场景，标题）</div>
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
    </div>
  );
}

