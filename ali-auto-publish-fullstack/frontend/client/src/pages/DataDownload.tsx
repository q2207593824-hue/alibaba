/**
 * DataDownload - 产品参谋数据下载页面
 * 对应脚本: cs_产品参谋_产品排名，访客，渠道下载.py + cs_产品参谋_日数据下载.py
 * 功能: 产品排名、访客地域、流量来源数据采集，日数据下载
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { toast } from "sonner";
import { configApi, dataApi, createLogSocket } from "@/lib/api";
import {
  Download,
  Play,
  Pause,
  BarChart3,
  Globe2,
  Layers,
  FileJson,
  FileSpreadsheet,
  ChevronRight,
  Clock,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Calendar,
  Database,
  ArrowDownToLine,
} from "lucide-react";

const PRODUCT360_TASK_TYPE = "product360";

// 对应脚本中的数据维度
const dataSheets = [
  { name: "产品详情", desc: "产品基础信息、排名、曝光数据", icon: BarChart3, status: "ready" },
  { name: "访客地域", desc: "按国家/地区统计的访客量分布", icon: Globe2, status: "ready" },
  { name: "流量来源", desc: "各流量渠道的访问、询盘、TM咨询数据", icon: Layers, status: "ready" },
];

// 模拟采集记录
const mockRecords = [
  { date: "2026-03-16", products: 45, status: "done", files: 135 },
  { date: "2026-03-15", products: 45, status: "done", files: 135 },
  { date: "2026-03-14", products: 42, status: "done", files: 126 },
  { date: "2026-03-13", products: 45, status: "done", files: 135 },
  { date: "2026-03-12", products: 43, status: "done", files: 129 },
];

// 日数据下载记录

export default function DataDownload() {
  const [isRunning, setIsRunning] = useState(false);
  const [logs, setLogs] = useState<string[]>([
    "[系统] 产品参谋数据下载模块已就绪",
  ]);
  const [outputDir, setOutputDir] = useState("");
  const [product360JsonDir, setProduct360JsonDir] = useState("");
  const [product360KeywordJsonDir, setProduct360KeywordJsonDir] = useState("");
  const [product360ExcelResultDir, setProduct360ExcelResultDir] = useState("");
  const [taskStatus, setTaskStatus] = useState<any>(null);
  const [product360Files, setProduct360Files] = useState<any[]>([]);
  const [dimTable, setDimTable] = useState<any>({ sheet: "", sheets: [], columns: [], rows: [] });
  const [dimSheet, setDimSheet] = useState("产品详细信息");
  const [dimSortKey, setDimSortKey] = useState<string>("产品综合搜索排名");
  const [dimSortDir, setDimSortDir] = useState<"asc" | "desc">("desc");
  const [dimQueryBySheet, setDimQueryBySheet] = useState<Record<string, string>>({});

  const [dailyOutputDir, setDailyOutputDir] = useState("");
  const [weeklyOutputDir, setWeeklyOutputDir] = useState("");
  const [dailyTaskStatus, setDailyTaskStatus] = useState<any>(null);
  const [dailyRunning, setDailyRunning] = useState(false);
  const [dailyStopping, setDailyStopping] = useState(false);
  const [dailyLogs, setDailyLogs] = useState<string[]>(["[系统] 日数据下载模块已就绪"]);
  const [dailyFiles, setDailyFiles] = useState<any[]>([]);
  const lastProductStatusLogRef = useRef("");
  const lastDailyStatusLogRef = useRef("");
  const dailyWasRunningRef = useRef(false);
  const product360WasRunningRef = useRef(false);

  const loadConfig = async () => {
    try {
      const [dd, da] = await Promise.all([
        configApi.getSection("data_download").catch(() => ({})),
        configApi.getSection("data_analysis").catch(() => ({}))
      ]);
      const dir = dd?.product360_output_dir || "";
      const jsonDir = dd?.product360_json_dir || (dir ? `${dir}\\Json文件` : "");
      const keywordDir = dd?.product360_keyword_json_dir || (dir ? `${dir}\\关键词json` : "");
      const excelDir = dd?.product360_excel_result_dir || (dir ? `${dir}\\Excel结果` : "");
      
      // 联动：优先读取 data_analysis 中的 source_dir 和 single_analysis_input_file
      const dailyDir = da?.source_dir || dd?.daily_output_dir || "";
      const weeklyDir = da?.single_analysis_input_file || dd?.weekly_output_dir || "";
      
      setOutputDir(dir);
      setProduct360JsonDir(jsonDir);
      setProduct360KeywordJsonDir(keywordDir);
      setProduct360ExcelResultDir(excelDir);
      setDailyOutputDir(dailyDir);
      setWeeklyOutputDir(weeklyDir);
    } catch (e: any) {
      toast.error(e.message || "加载配置失败");
    }
  };

  const saveProduct360Config = async () => {
    try {
      const current = (await configApi.getSection("data_download")) || {};
      await configApi.updateSection("data_download", {
        ...current,
        product360_output_dir: outputDir,
        product360_json_dir: product360JsonDir,
        product360_keyword_json_dir: product360KeywordJsonDir,
        product360_excel_result_dir: product360ExcelResultDir,
      });
      toast.success("产品360配置已保存");
    } catch (e: any) {
      toast.error(e.message || "保存失败");
    }
  };

  const saveDailyConfig = async () => {
    try {
      const [currentDD, currentDA] = await Promise.all([
        configApi.getSection("data_download").catch(() => ({})),
        configApi.getSection("data_analysis").catch(() => ({}))
      ]);
      
      // 同时更新 data_download 和 data_analysis，实现双向绑定
      await Promise.all([
        configApi.updateSection("data_download", {
          ...currentDD,
          daily_output_dir: dailyOutputDir,
          weekly_output_dir: weeklyOutputDir,
        }),
        configApi.updateSection("data_analysis", {
          ...currentDA,
          source_dir: dailyOutputDir,
          single_analysis_input_file: weeklyOutputDir,
        })
      ]);
      
      toast.success("日数据与综合分析目录已同步保存");
    } catch (e: any) {
      toast.error(e.message || "保存失败");
    }
  };

  const refreshStatus = async () => {
    try {
      const res = await dataApi.getDownloadStatus(PRODUCT360_TASK_TYPE);
      const data = res?.data || res;
      const status = data?.data || data;
      setTaskStatus(status);
      const running = status?.status === "running" || status?.status === "stopping";
      const wasRunning = product360WasRunningRef.current;
      product360WasRunningRef.current = running;
      setIsRunning(running);
      if (wasRunning && !running && (status?.status === "completed" || status?.status === "failed")) {
        refreshProduct360Files();
        refreshDimTable(dimSheet || "产品详细信息");
      }
      const raw = `${status?.status || ""}|${status?.current_step || ""}|${status?.error || ""}`;
      if (raw && raw !== lastProductStatusLogRef.current) {
        lastProductStatusLogRef.current = raw;
        const msg = status?.error
          ? `[任务] ${status?.current_step || "执行异常"} | 错误: ${status.error}`
          : `[任务] ${status?.current_step || (status?.status || "状态更新")}`;
        setLogs((prev) => [...prev, msg].slice(-500));
      }
    } catch {
      // ignore
    }
  };

  const refreshDailyFiles = async () => {
    try {
      const dailyDir = normalizePath(dailyOutputDir);
      const weeklyDir = normalizePath(weeklyOutputDir);
      const [dailyRes, weeklyRes] = await Promise.all([
        dailyDir ? dataApi.getFiles(dailyDir) : Promise.resolve({ data: [] }),
        weeklyDir && weeklyDir !== dailyDir ? dataApi.getFiles(weeklyDir) : Promise.resolve({ data: [] }),
      ]);
      const parseItems = (res: any) => {
        const payload = res?.data ?? res;
        const data = Array.isArray(payload) ? payload : payload?.data || payload || {};
        return Array.isArray(data?.items) ? data.items : Array.isArray(data) ? data : [];
      };
      const dailyItems = parseItems(dailyRes).map((f: any) => ({ ...f, __period: "日" }));
      const weeklyItems =
        weeklyDir && weeklyDir !== dailyDir
          ? parseItems(weeklyRes).map((f: any) => ({ ...f, __period: "周" }))
          : [];
      setDailyFiles([...weeklyItems, ...dailyItems]);
    } catch {
      // ignore
    }
  };

  const refreshProduct360Files = async () => {
    try {
      const root = normalizePath(outputDir || "");
      const jsonDir = normalizePath(product360JsonDir || (root ? `${root}\\Json文件` : ""));
      const keywordDir = normalizePath(product360KeywordJsonDir || (root ? `${root}\\关键词json` : ""));

      if (!jsonDir && !keywordDir) {
        setProduct360Files([]);
        return;
      }

      const [originRes, keywordRes] = await Promise.all([
        jsonDir ? dataApi.getFiles(jsonDir) : Promise.resolve({ data: [] }),
        keywordDir ? dataApi.getFiles(keywordDir) : Promise.resolve({ data: [] }),
      ]);
      const p1 = originRes?.data ?? originRes;
      const p2 = keywordRes?.data ?? keywordRes;
      const files1 = (Array.isArray(p1) ? p1 : p1?.data || []).map((f: any) => ({ ...f, __source: "origin" }));
      const files2 = (Array.isArray(p2) ? p2 : p2?.data || []).map((f: any) => ({ ...f, __source: "keyword" }));
      setProduct360Files([...(files1 || []), ...(files2 || [])]);
    } catch {
      // ignore
    }
  };

  const refreshDimTable = async (sheet?: string) => {
    try {
      const excelDir = normalizePath(product360ExcelResultDir || "");
      const res = await dataApi.getProduct360Table(excelDir, sheet || dimSheet || undefined);
      const payload = res?.data ?? res;
      const data = payload?.data ?? payload;
      setDimTable(data || { sheet: "", sheets: [], columns: [], rows: [] });
      if (!dimSheet && data?.sheet) setDimSheet(data.sheet);
      const nextSheet = data?.sheet || sheet || dimSheet || "";
      if (nextSheet === "产品详细信息") {
        setDimSortKey("产品综合搜索排名");
        setDimSortDir("desc");
      } else {
        setDimSortKey("");
        setDimSortDir("desc");
      }
    } catch {
      setDimTable({ sheet: "", sheets: [], columns: [], rows: [] });
      setDimSortKey("");
      setDimSortDir("desc");
    }
  };

  const refreshDailyStatus = async () => {
    try {
      const res = await dataApi.getDownloadStatus("daily_data");
      const data = res?.data || res;
      const status = data?.data || data;
      setDailyTaskStatus(status);
      const running = status?.status === "running" || status?.status === "stopping";
      const stopping = status?.status === "stopping";
      const wasRunning = dailyWasRunningRef.current;
      dailyWasRunningRef.current = running;
      setDailyRunning(running && !stopping);
      setDailyStopping(stopping);
      if (wasRunning && !running && (status?.status === "completed" || status?.status === "failed")) {
        refreshDailyFiles();
        if (status?.status === "failed") {
          toast.error(status?.error || status?.current_step || "日数据下载失败");
        } else if (status?.status === "completed" && (status?.current_step || "").includes("日数据新增 0")) {
          toast.warning(status.current_step || "日数据未新增文件，请查看运行日志");
        } else if (status?.status === "completed" && (status?.current_step || "").includes("下载与分析已全部完成")) {
          toast.success("日数据下载与自动分析已完成");
        }
      }
      const raw = `${status?.status || ""}|${status?.current_step || ""}|${status?.error || ""}`;
      if (raw && raw !== lastDailyStatusLogRef.current) {
        lastDailyStatusLogRef.current = raw;
        const msg = status?.error
          ? `[任务] ${status?.current_step || "执行异常"} | 错误: ${status.error}`
          : `[任务] ${status?.current_step || (status?.status || "状态更新")}`;
        setDailyLogs((prev) => [...prev, msg].slice(-500));
      }
      return status ?? null;
    } catch {
      return null;
    }
  };

  const handleStart = async () => {
    try {
      if (!outputDir) {
        toast.error("请先配置输出目录");
        return;
      }
      setIsRunning(true);
      setLogs((prev) => [
        ...prev,
        `[${new Date().toLocaleTimeString()}] 开始产品360下载（采集完成后将自动生成 Excel）...`,
      ]);
      await dataApi.startDownload({ task_type: PRODUCT360_TASK_TYPE });
      toast.success("产品360下载已启动");
      refreshStatus();
    } catch (e: any) {
      toast.error(e.message || "启动失败");
      setIsRunning(false);
    }
  };

  const handleStop = async () => {
    try {
      await dataApi.stopDownload(PRODUCT360_TASK_TYPE);
      toast.info("已停止");
      refreshStatus();
      setIsRunning(false);
    } catch (e: any) {
      toast.error(e.message || "停止失败");
    }
  };

  const handleDailyStart = async () => {
    if (dailyRunning || dailyStopping) return;
    try {
      if (!dailyOutputDir?.trim() || !weeklyOutputDir?.trim()) {
        toast.error("请先配置日数据目录和周数据目录");
        return;
      }
      setDailyLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] 开始日数据下载...`]);
      const res = await dataApi.startDownload({ task_type: "daily_data" });
      const payload = res?.data ?? res;
      if (payload?.success === false) {
        throw new Error(payload?.message || payload?.detail || "启动失败");
      }
      setDailyRunning(true);
      toast.success("日数据下载已启动");
      const st = await refreshDailyStatus();
      if (st?.status === "failed") {
        setDailyRunning(false);
        toast.error(st?.error || "日数据下载启动后立即失败，请查看日志");
      }
    } catch (e: any) {
      const msg =
        e?.response?.data?.detail ||
        e?.data?.detail ||
        e?.message ||
        "启动失败";
      toast.error(typeof msg === "string" ? msg : JSON.stringify(msg));
      setDailyRunning(false);
      setDailyLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] 启动失败: ${msg}`].slice(-500));
      await refreshDailyStatus();
    }
  };

  const handleDailyStop = async () => {
    try {
      setDailyStopping(true);
      setDailyRunning(false);
      setDailyLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] 正在停止...`]);
      await dataApi.stopDownload("daily_data");
      toast.info("停止指令已发送");
      refreshDailyStatus();
    } catch (e: any) {
      toast.error(e.message || "停止失败");
      setDailyStopping(false);
    }
  };

  const normalizePath = (input: string) => input.trim().replace(/[/]+/g, "\\");

  useEffect(() => {
    loadConfig();
  }, []);

  useEffect(() => {
    refreshStatus();
    refreshDailyStatus();
    refreshDailyFiles();
    const intervalMs = dailyRunning || dailyStopping || isRunning ? 800 : 10000;
    const timer = setInterval(() => {
      const isVisible = typeof document === "undefined" ? true : document.visibilityState === "visible";
      if (!isVisible && !isRunning && !dailyRunning && !dailyStopping) return;
      if (!isRunning && !dailyRunning && !dailyStopping) return;
      refreshStatus();
      refreshDailyStatus();
      if (dailyRunning || dailyStopping || isRunning) {
        refreshDailyFiles();
      }
    }, intervalMs);
    return () => clearInterval(timer);
  }, [dailyOutputDir, isRunning, dailyRunning, dailyStopping, dimSheet]);

  useEffect(() => {
    refreshProduct360Files();
    refreshDimTable(dimSheet || "产品详细信息");
  }, [outputDir, product360ExcelResultDir]);

  useEffect(() => {
    if (!normalizePath(product360ExcelResultDir || "")) return;
    refreshDimTable(dimSheet || undefined);
  }, [dimSheet, product360ExcelResultDir]);

  const dimSortable = (c: string) => {
    if (dimSheet !== "产品详细信息") return false;
    return c !== "产品ID" && c !== "各流量渠道UV分布";
  };

  const dimOnSort = (c: string) => {
    if (!dimSortable(c)) return;
    if (dimSortKey === c) setDimSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setDimSortKey(c);
      setDimSortDir("desc");
    }
  };

  const dimSortMark = (c: string) => (dimSortKey === c ? (dimSortDir === "asc" ? "↑" : "↓") : "");

  const dimRowsSorted = [...(dimTable.rows || [])].sort((a: any, b: any) => {
    if (!dimSortKey || !dimSortable(dimSortKey)) return 0;
    const avRaw = a?.[dimSortKey];
    const bvRaw = b?.[dimSortKey];
    const avNum = Number(String(avRaw ?? "").replace(/,/g, ""));
    const bvNum = Number(String(bvRaw ?? "").replace(/,/g, ""));

    if (Number.isFinite(avNum) || Number.isFinite(bvNum)) {
      const left = Number.isFinite(avNum) ? avNum : 0;
      const right = Number.isFinite(bvNum) ? bvNum : 0;
      return dimSortDir === "asc" ? left - right : right - left;
    }

    const as = String(avRaw ?? "");
    const bs = String(bvRaw ?? "");
    return dimSortDir === "asc" ? as.localeCompare(bs) : bs.localeCompare(as);
  });

  const dimQuery = (dimQueryBySheet?.[dimSheet] || "").trim();

  const dimRowsDisplay = useMemo(() => {
    if (!dimQuery) return dimRowsSorted;
    const q = dimQuery.toLowerCase();
    const cols: string[] = Array.isArray(dimTable?.columns) ? dimTable.columns : [];
    return dimRowsSorted.filter((row: any) => {
      for (const c of cols) {
        const v = String(row?.[c] ?? "");
        if (v.toLowerCase().includes(q)) return true;
      }
      return false;
    });
  }, [dimQuery, dimRowsSorted, dimTable?.columns]);

  const originalJsonFiles = (product360Files || []).filter((f: any) => f?.__source !== "keyword");
  const keywordJsonFiles = (product360Files || []).filter((f: any) => f?.__source === "keyword");

  useEffect(() => {
    const ws = createLogSocket((data) => {
      if (!data) return;
      const payload = data.data || data;
      const moduleName = String(payload?.module || "");
      const msg = payload.message || payload.msg || payload.text;
      if (!msg) return;
      if (moduleName && moduleName !== "data_download") return;
      const text = String(msg);
      if (text.includes("文件目录") || text.includes("文件数量")) return;
      const isDailyLog =
        /日数据|daily_data|日粒度|周数据|Products-|切换到日|下载完成|导出失败|正在停止|已停止|综合分析|单品分析|流量分析|产品优化|自动分析/i.test(
          text
        );
      const isProductLog =
        text.includes("产品360") ||
        text.includes("产品参谋") ||
        text.includes("访客地域") ||
        text.includes("流量来源") ||
        text.includes("Json文件") ||
        text.includes("关键词json");
      if (isProductLog) {
        setLogs((prev) => {
          const next = [...prev, text];
          return next.slice(-500);
        });
      }
      if (isDailyLog) {
        setDailyLogs((prev) => {
          const next = [...prev, text];
          return next.slice(-500);
        });
      }
    });

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
          <span className="text-foreground">产品参谋数据</span>
        </div>
        <h1 className="text-2xl font-bold text-foreground">产品参谋数据下载</h1>
        <p className="text-sm text-muted-foreground mt-1">
          一键采集产品排名、访客地域、流量来源并自动生成 Excel 总报告
        </p>
      </div>

      <Tabs defaultValue="product360">
        <TabsList className="bg-muted/50">
          <TabsTrigger value="product360" className="gap-2">
            <Database className="w-3.5 h-3.5" />
            产品360数据
          </TabsTrigger>
          <TabsTrigger value="daily" className="gap-2">
            <Calendar className="w-3.5 h-3.5" />
            日数据下载
          </TabsTrigger>
        </TabsList>

        {/* Product 360 Data */}
        <TabsContent value="product360" className="mt-6">
          <div className="grid grid-cols-3 gap-6">
            <div className="col-span-2 space-y-6">
              <Card className="border-primary/20 bg-primary/5">
                <CardContent className="py-4">
                  <div className="flex items-start gap-3">
                    <div className="w-10 h-10 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0">
                      <Database className="w-5 h-5" />
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold">产品360 一键下载</h3>
                      <p className="text-xs text-muted-foreground mt-1">
                        启动浏览器采集各产品 JSON 数据，采集结束后自动解析并生成 Excel 总报告，无需分步操作。
                      </p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Control & Logs */}
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base">执行控制</CardTitle>
                    <div className="flex items-center gap-3">
                      <Badge variant={isRunning ? "default" : "secondary"} className="gap-1.5">
                        {isRunning ? (
                          <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                        ) : (
                          <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
                        )}
                        {isRunning ? "运行中" : "待启动"}
                      </Badge>
                      <Button
                        size="sm"
                        onClick={isRunning ? handleStop : handleStart}
                        variant={isRunning ? "destructive" : "default"}
                        className="gap-2"
                      >
                        {isRunning ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                        {isRunning ? "停止" : "开始"}
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <ScrollArea className="h-48 rounded-lg bg-gray-950 p-4">
                    <div className="space-y-1 font-mono text-xs">
                      {logs.map((log, i) => (
                        <div key={i} className="text-gray-300">{log}</div>
                      ))}
                    </div>
                  </ScrollArea>
                </CardContent>
              </Card>

              {/* Data Dimensions */}
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1 space-y-1">
                      <CardTitle className="text-base">数据维度</CardTitle>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        产品详细信息sheet显示的信息内容为近30天的数据，其余sheet均显示上一周的数据
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <Input
                        value={dimQueryBySheet?.[dimSheet] || ""}
                        onChange={(e) => {
                          const v = e.target.value;
                          setDimQueryBySheet((prev) => ({ ...(prev || {}), [dimSheet]: v }));
                        }}
                        placeholder="搜索（当前sheet）"
                        className="h-8 w-44 text-xs"
                      />
                      <select className="h-8 rounded border border-input bg-background px-2 text-xs" value={dimSheet} onChange={(e) => setDimSheet(e.target.value)}>
                        {(dimTable.sheets || []).map((s: string) => (
                          <option key={s} value={s}>{s}</option>
                        ))}
                      </select>
                      <Button size="sm" variant="ghost" onClick={() => refreshDimTable(dimSheet || undefined)}>刷新</Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="h-[420px] overflow-auto rounded-lg border border-border/50">
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                        <tr className="border-b">
                          {(dimTable.columns || []).length === 0 ? (
                            <th className="text-left py-3 px-3 font-medium text-xs text-muted-foreground">暂无列</th>
                          ) : (dimTable.columns || []).map((c: string) => (
                            <th
                              key={c}
                              className={`py-3 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap text-left ${dimSortable(c) ? "cursor-pointer select-none" : ""}`}
                              onClick={() => dimOnSort(c)}
                            >
                              {c}{dimSortMark(c) ? ` ${dimSortMark(c)}` : ""}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {dimRowsDisplay.length === 0 ? (
                          <tr>
                            <td colSpan={Math.max((dimTable.columns || []).length, 1)} className="py-6 text-center text-xs text-muted-foreground">
                              {dimQuery ? "无匹配结果" : "暂无数据（请先完成产品360下载）"}
                            </td>
                          </tr>
                        ) : dimRowsDisplay.map((row: any, i: number) => (
                          <tr key={i} className="border-b last:border-0 hover:bg-accent/30">
                            {(dimTable.columns || []).map((c: string) => (
                              <td key={c} className="py-2.5 px-3 text-xs whitespace-nowrap">{String(row?.[c] ?? "")}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Right: Records */}
            <div className="space-y-4">
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm">采集记录（Json文件）</CardTitle>
                    <Button size="sm" variant="ghost" onClick={refreshProduct360Files}>刷新</Button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div>
                    <div className="mb-1.5 text-xs font-medium text-muted-foreground">原始采集JSON（产品详情/访客地域/流量来源）</div>
                    <div className="h-36 overflow-y-auto rounded-lg border border-border/50">
                      {originalJsonFiles.length === 0 ? (
                        <div className="py-6 text-center text-xs text-muted-foreground">暂无文件</div>
                      ) : (
                        <div className="divide-y">
                          {originalJsonFiles.map((file) => (
                            <div key={file.path || file.name} className="flex items-center justify-between p-2.5">
                              <div className="text-xs font-mono truncate max-w-[180px]">{file.name}</div>
                              <div className="text-[10px] text-muted-foreground">
                                {file.size_bytes ? `${Math.round(file.size_bytes / 1024)}KB` : "--"}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>

                  <div>
                    <div className="mb-1.5 text-xs font-medium text-muted-foreground">关键词JSON</div>
                    <div className="h-28 overflow-y-auto rounded-lg border border-border/50">
                      {keywordJsonFiles.length === 0 ? (
                        <div className="py-6 text-center text-xs text-muted-foreground">暂无文件</div>
                      ) : (
                        <div className="divide-y">
                          {keywordJsonFiles.map((file) => (
                            <div key={file.path || file.name} className="flex items-center justify-between p-2.5">
                              <div className="text-xs font-mono truncate max-w-[180px]">{file.name}</div>
                              <div className="text-[10px] text-muted-foreground">
                                {file.size_bytes ? `${Math.round(file.size_bytes / 1024)}KB` : "--"}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm">配置</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">输出根目录</Label>
                    <Input
                      value={outputDir}
                      onChange={(e) => setOutputDir(e.target.value)}
                      placeholder="D:\\Users\\mikey\\Desktop\\产品分析\\详细分析cs"
                      className="text-xs font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">Json文件路径</Label>
                    <Input
                      value={product360JsonDir}
                      onChange={(e) => setProduct360JsonDir(e.target.value)}
                      placeholder="D:\\Users\\mikey\\Desktop\\产品分析\\详细分析cs\\Json文件"
                      className="text-xs font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">关键词json路径</Label>
                    <Input
                      value={product360KeywordJsonDir}
                      onChange={(e) => setProduct360KeywordJsonDir(e.target.value)}
                      placeholder="D:\\Users\\mikey\\Desktop\\产品分析\\详细分析cs\\关键词json"
                      className="text-xs font-mono"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">Excel结果路径</Label>
                    <Input
                      value={product360ExcelResultDir}
                      onChange={(e) => setProduct360ExcelResultDir(e.target.value)}
                      placeholder="D:\\Users\\mikey\\Desktop\\产品分析\\详细分析cs\\Excel结果"
                      className="text-xs font-mono"
                    />
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button size="sm" variant="outline" onClick={saveProduct360Config}>保存配置</Button>
                    <Button size="sm" variant="ghost" onClick={loadConfig}>重载</Button>
                  </div>
                  <Separator />
                  <div className="text-[11px] text-muted-foreground">
                    说明：点击「开始」将自动完成 JSON 采集与 Excel 生成；可分别配置各输出目录。
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        {/* Daily Data Download */}
        <TabsContent value="daily" className="mt-6">
          <div className="grid grid-cols-3 gap-6">
            <div className="col-span-2 space-y-4">
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base">日数据下载</CardTitle>
                    <div className="flex items-center gap-2">
                      <Badge variant={dailyRunning || dailyStopping ? "default" : "secondary"} className="gap-1.5">
                        {dailyStopping ? (
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                        ) : dailyRunning ? (
                          <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                        ) : (
                          <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
                        )}
                        {dailyStopping ? "停止中" : dailyRunning ? "运行中" : "待启动"}
                      </Badge>
                      <Button
                        size="sm"
                        onClick={dailyRunning || dailyStopping ? handleDailyStop : handleDailyStart}
                        className="gap-2"
                        variant={dailyRunning || dailyStopping ? "destructive" : "default"}
                        disabled={dailyStopping}
                        type="button"
                      >
                        {dailyRunning || dailyStopping ? <Pause className="w-3.5 h-3.5" /> : <ArrowDownToLine className="w-3.5 h-3.5" />}
                        {dailyStopping ? "停止中..." : dailyRunning ? "停止" : "开始下载"}
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <ScrollArea className="h-48 rounded-lg bg-gray-950 p-4">
                    <div className="space-y-1 font-mono text-xs">
                      {dailyLogs.map((log, i) => (
                        <div key={i} className="text-gray-300">{log}</div>
                      ))}
                    </div>
                  </ScrollArea>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm">日数据下载记录</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="h-56 overflow-y-auto rounded-lg border border-border/50">
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                        <tr className="border-b">
                          <th className="text-left py-3 px-4 font-medium text-xs text-muted-foreground">类型</th>
                          <th className="text-left py-3 px-4 font-medium text-xs text-muted-foreground">日期</th>
                          <th className="text-left py-3 px-4 font-medium text-xs text-muted-foreground">文件名</th>
                          <th className="text-left py-3 px-4 font-medium text-xs text-muted-foreground">大小</th>
                          <th className="text-left py-3 px-4 font-medium text-xs text-muted-foreground">状态</th>
                        </tr>
                      </thead>
                      <tbody>
                        {dailyFiles.length === 0 ? (
                          <tr>
                            <td colSpan={5} className="py-6 text-center text-xs text-muted-foreground">暂无文件</td>
                          </tr>
                        ) : (
                          dailyFiles.map((record) => (
                            <tr key={record.path || record.name} className="border-b last:border-0 hover:bg-accent/30">
                              <td className="py-3 px-4 text-xs text-muted-foreground">{record.__period || "日"}</td>
                              <td className="py-3 px-4 text-xs">
                                {record.mtime
                                  ? new Date(record.mtime * 1000).toLocaleDateString()
                                  : record.modified
                                    ? new Date(record.modified * 1000).toLocaleDateString()
                                    : "--"}
                              </td>
                              <td className="py-3 px-4 text-xs font-mono">{record.name}</td>
                              <td className="py-3 px-4 text-xs text-muted-foreground">
                                {record.size ? `${Math.round(record.size / 1024)}KB` : record.size_bytes ? `${Math.round(record.size_bytes / 1024)}KB` : "--"}
                              </td>
                              <td className="py-3 px-4">
                                <Badge variant="outline" className="text-[10px] h-5 bg-emerald-50 text-emerald-600 border-emerald-200">
                                  已下载
                                </Badge>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            </div>
            <div>
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm">下载配置</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">日数据存放目录</Label>
                    <Input value={dailyOutputDir} onChange={(e) => setDailyOutputDir(e.target.value)} placeholder="D:\产品日数据分析" className="text-xs font-mono" />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">周数据存放目录</Label>
                    <Input value={weeklyOutputDir} onChange={(e) => setWeeklyOutputDir(e.target.value)} placeholder="D:\产品周数据分析" className="text-xs font-mono" />
                  </div>
                  <div className="flex items-center gap-2">
                    <Button size="sm" variant="outline" onClick={saveDailyConfig}>保存配置</Button>
                    <Button size="sm" variant="ghost" onClick={loadConfig}>重载</Button>
                    <Button size="sm" variant="ghost" onClick={refreshDailyFiles}>刷新文件</Button>
                  </div>
                  <Separator />
                  <div className="p-3 bg-amber-50 rounded-lg border border-amber-100 mt-3">
                    <p className="text-[11px] text-amber-700">
                      日数据任务按老脚本流程：独立浏览器 → 切「日」粒度 → 逐日导出到「日数据目录」。下方列表会同时展示周/日目录中的文件。
                    </p>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
