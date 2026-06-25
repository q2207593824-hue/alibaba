import { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ChevronRight, Play, Pause, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { configApi, createLogSocket, dataApi } from "@/lib/api";

export default function TrafficChannelDownload() {
  const [isRunning, setIsRunning] = useState(false);
  const [logs, setLogs] = useState<string[]>(["[系统] 流量渠道下载模块已就绪"]);

  const [outputFile, setOutputFile] = useState("");

  const [sheet, setSheet] = useState("");
  const [sheets, setSheets] = useState<string[]>([]);
  const [todayRows, setTodayRows] = useState<any[]>([]);
  const [weekRows, setWeekRows] = useState<any[]>([]);
  const [monthRows, setMonthRows] = useState<any[]>([]);
  const [analysis, setAnalysis] = useState<{ columns: string[]; rows: any[] }>({ columns: [], rows: [] });

  const taskType = "traffic_channel";
  const conversionWarnThreshold = 0.03;

  const channelPriority = ["搜索", "系统推荐", "导购会场", "直接访问", "店内", "站外", "其他"];
  const [todaySortKey, setTodaySortKey] = useState<"__default" | "店铺访问人数" | "店内询盘人数" | "店内TM咨询人数" | "商机转化率">("__default");
  const [todaySortDir, setTodaySortDir] = useState<"asc" | "desc">("desc");
  const [weekSortKey, setWeekSortKey] = useState<"__default" | "店铺访问人数" | "店内询盘人数" | "店内TM咨询人数" | "商机转化率">("__default");
  const [weekSortDir, setWeekSortDir] = useState<"asc" | "desc">("desc");
  const [monthSortKey, setMonthSortKey] = useState<"__default" | "店铺访问人数" | "店内询盘人数" | "店内TM咨询人数" | "商机转化率">("__default");
  const [monthSortDir, setMonthSortDir] = useState<"asc" | "desc">("desc");
  const lastStatusLogRef = useRef("");

  const loadConfig = async () => {
    try {
      const dd = (await configApi.getSection("data_download")) || {};
      setOutputFile(dd?.traffic_channel_output_file || "");
    } catch (e: any) {
      toast.error(e.message || "加载配置失败");
    }
  };

  const saveConfig = async () => {
    try {
      const current = (await configApi.getSection("data_download")) || {};
      await configApi.updateSection("data_download", {
        ...current,
        traffic_channel_output_file: outputFile,
      });
      toast.success("流量渠道配置已保存");
      refreshOverview(sheet || "搜索");
    } catch (e: any) {
      toast.error(e.message || "保存失败");
    }
  };

  const refreshStatus = async () => {
    try {
      const res = await dataApi.getDownloadStatus(taskType);
      const payload = res?.data || res;
      const s = payload?.data || payload;
      setIsRunning(s?.status === "running" || s?.status === "stopping");
      const raw = `${s?.status || ""}|${s?.current_step || ""}|${s?.error || ""}`;
      if (raw && raw !== lastStatusLogRef.current) {
        lastStatusLogRef.current = raw;
        const msg = s?.error
          ? `[任务] ${s?.current_step || "执行异常"} | 错误: ${s.error}`
          : `[任务] ${s?.current_step || (s?.status || "状态更新")}`;
        setLogs((prev) => [...prev, msg].slice(-500));
      }
    } catch {
      // ignore
    }
  };

  const refreshOverview = async (sheetName?: string) => {
    try {
      const res = await dataApi.getTrafficChannelOverview(outputFile || undefined, sheetName || sheet || undefined);
      const payload = res?.data || res;
      const data = payload?.data || payload;

      const nextSheets = Array.isArray(data?.sheets) ? data.sheets : [];
      const nextSheet = String(data?.sheet || "");
      const preferredSheet = nextSheets.includes("搜索") ? "搜索" : "";
      const finalSheet = String(sheetName || nextSheet || preferredSheet || nextSheets[0] || "");

      setSheets(nextSheets);
      setSheet(finalSheet);
      setTodayRows(Array.isArray(data?.today) ? data.today : []);
      setWeekRows(Array.isArray(data?.week) ? data.week : []);
      setMonthRows(Array.isArray(data?.month) ? data.month : []);
      setAnalysis({
        columns: Array.isArray(data?.analysis?.columns) ? data.analysis.columns : [],
        rows: Array.isArray(data?.analysis?.rows) ? data.analysis.rows : [],
      });
    } catch {
      setTodayRows([]);
      setWeekRows([]);
      setMonthRows([]);
      setAnalysis({ columns: [], rows: [] });
    }
  };

  const handleStart = async () => {
    try {
      if (!outputFile) {
        toast.error("请先配置输出文件路径");
        return;
      }

      // 启动前先保存配置，避免后端读取旧路径导致任务未实际执行
      const current = (await configApi.getSection("data_download")) || {};
      await configApi.updateSection("data_download", {
        ...current,
        traffic_channel_output_file: outputFile,
        traffic_channel_target_url: "https://data.alibaba.com/traffic/source?spm=a2700.micro_cgs_home.0.0.54d63e5fh024lb",
        traffic_channel_login_url: "https://login.alibaba.com/newlogin/icbuLogin.htm",
      });

      setIsRunning(true);
      setLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] 开始流量渠道下载...`]);
      await dataApi.startDownload({ task_type: taskType });
      toast.success("流量渠道下载已启动");
      refreshStatus();
      refreshOverview(sheet || "搜索");
    } catch (e: any) {
      toast.error(e.message || "启动失败");
      setIsRunning(false);
    }
  };

  const handleStop = async () => {
    try {
      await dataApi.stopDownload(taskType);
      toast.info("已停止");
      refreshStatus();
      setIsRunning(false);
    } catch (e: any) {
      toast.error(e.message || "停止失败");
    }
  };

  const stats = useMemo(() => {
    const sum = (rows: any[]) => rows.reduce((acc, r) => acc + Number(r?.["店铺访问人数"] || 0), 0);
    const ask = (rows: any[]) => rows.reduce((acc, r) => acc + Number(r?.["店内询盘人数"] || 0), 0);
    const tm = (rows: any[]) => rows.reduce((acc, r) => acc + Number(r?.["店内TM咨询人数"] || 0), 0);
    return {
      today: { uv: sum(todayRows), ask: ask(todayRows), tm: tm(todayRows) },
      week: { uv: sum(weekRows), ask: ask(weekRows), tm: tm(weekRows) },
      month: { uv: sum(monthRows), ask: ask(monthRows), tm: tm(monthRows) },
    };
  }, [todayRows, weekRows, monthRows]);

  const matchPriority = (name: string): number => {
    const s = String(name || "");
    const idx = channelPriority.findIndex((k) => s.includes(k));
    return idx === -1 ? 999 : idx;
  };

  const defaultOrdered = (rows: any[]) => {
    return [...(rows || [])].sort((a, b) => {
      const pa = matchPriority(a?.["流量渠道"]);
      const pb = matchPriority(b?.["流量渠道"]);
      if (pa !== pb) return pa - pb;
      return String(a?.["流量渠道"] || "").localeCompare(String(b?.["流量渠道"] || ""));
    });
  };

  const sortedRows = (
    rows: any[],
    sortKey: "__default" | "店铺访问人数" | "店内询盘人数" | "店内TM咨询人数" | "商机转化率",
    sortDir: "asc" | "desc"
  ) => {
    if (sortKey === "__default") return defaultOrdered(rows);
    const ordered = defaultOrdered(rows);
    return ordered.sort((a, b) => {
      const av = Number(a?.[sortKey] || 0);
      const bv = Number(b?.[sortKey] || 0);
      return sortDir === "asc" ? av - bv : bv - av;
    });
  };

  const renderSummaryTable = (
    title: string,
    rows: any[],
    sortKey: "__default" | "店铺访问人数" | "店内询盘人数" | "店内TM咨询人数" | "商机转化率",
    sortDir: "asc" | "desc",
    onSort: (key: "店铺访问人数" | "店内询盘人数" | "店内TM咨询人数" | "商机转化率") => void
  ) => {
    const finalRows = sortedRows(rows, sortKey, sortDir);
    const mark = (k: string) => (sortKey === k ? (sortDir === "asc" ? " ↑" : " ↓") : "");

    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-56 overflow-auto rounded-lg border border-border/50">
            <table className="w-full text-sm min-w-[560px]">
              <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                <tr className="border-b">
                  <th className="text-left py-2.5 px-3 text-xs text-muted-foreground">流量渠道</th>
                  <th onClick={() => onSort("店铺访问人数")} className="cursor-pointer text-right py-2.5 px-3 text-xs text-muted-foreground">店铺访问人数{mark("店铺访问人数")}</th>
                  <th onClick={() => onSort("店内询盘人数")} className="cursor-pointer text-right py-2.5 px-3 text-xs text-muted-foreground">店内询盘人数{mark("店内询盘人数")}</th>
                  <th onClick={() => onSort("店内TM咨询人数")} className="cursor-pointer text-right py-2.5 px-3 text-xs text-muted-foreground">店内TM咨询人数{mark("店内TM咨询人数")}</th>
                  <th onClick={() => onSort("商机转化率")} className="cursor-pointer text-right py-2.5 px-3 text-xs text-muted-foreground">商机转化率{mark("商机转化率")}</th>
                </tr>
              </thead>
              <tbody>
                {finalRows.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="py-6 text-center text-xs text-muted-foreground">暂无数据</td>
                  </tr>
                ) : finalRows.map((r, i) => (
                  <tr key={`${title}-${i}`} className="border-b last:border-0 hover:bg-accent/30">
                    <td className="py-2 px-3 text-xs">{String(r?.["流量渠道"] ?? "")}</td>
                    <td className="py-2 px-3 text-xs text-right">{Math.round(Number(r?.["店铺访问人数"] || 0)).toLocaleString()}</td>
                    <td className="py-2 px-3 text-xs text-right">{Math.round(Number(r?.["店内询盘人数"] || 0)).toLocaleString()}</td>
                    <td className="py-2 px-3 text-xs text-right">{Math.round(Number(r?.["店内TM咨询人数"] || 0)).toLocaleString()}</td>
                    <td className="py-2 px-3 text-xs text-right">{(Number(r?.["商机转化率"] || 0) * 100).toFixed(2)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    );
  };

  useEffect(() => {
    loadConfig();
  }, []);

  useEffect(() => {
    void refreshStatus();
  }, []);

  useEffect(() => {
    if (!isRunning) return;
    const timer = setInterval(refreshStatus, 3000);
    return () => clearInterval(timer);
  }, [isRunning]);

  useEffect(() => {
    if (!outputFile) return;
    refreshOverview("搜索");
  }, [outputFile]);

  useEffect(() => {
    if (!sheet) return;
    refreshOverview(sheet);
  }, [sheet]);

  useEffect(() => {
    const ws = createLogSocket((data) => {
      if (!data) return;
      const payload = data.data || data;
      const moduleName = String(payload?.module || "");
      const msg = payload.message || payload.msg || payload.text;
      if (!msg) return;
      if (moduleName && moduleName !== "data_download") return;
      const text = String(msg);
      if (!text.includes("流量渠道")) return;
      setLogs((prev) => {
        const next = [...prev, text];
        return next.slice(-500);
      });
    });

    return () => {
      try {
        ws?.close();
      } catch {
        // ignore
      }
    };
  }, []);

  const analysisRateByCol = useMemo(() => {
    const rows = Array.isArray(analysis.rows) ? analysis.rows : [];
    const cols = Array.isArray(analysis.columns) ? analysis.columns : [];
    const metricKey = cols.includes("指标") ? "指标" : (cols.includes("指标名称") ? "指标名称" : "");
    if (!metricKey) return {} as Record<string, number>;

    const uvRow = rows.find((r) => String(r?.[metricKey] ?? "").trim() === "店铺访问人数");
    const askRow = rows.find((r) => String(r?.[metricKey] ?? "").trim() === "店内询盘人数");
    const tmRow = rows.find((r) => String(r?.[metricKey] ?? "").trim() === "店内TM咨询人数");
    if (!uvRow || !askRow || !tmRow) return {} as Record<string, number>;

    const out: Record<string, number> = {};
    cols.forEach((c) => {
      if (c === metricKey) return;
      const uv = Number(uvRow?.[c] ?? 0);
      const ask = Number(askRow?.[c] ?? 0);
      const tm = Number(tmRow?.[c] ?? 0);
      out[c] = Number.isFinite(uv) && uv > 0 ? (ask + tm) / uv : 0;
    });
    return out;
  }, [analysis]);

  return (
    <div className="p-8">
      <div className="mb-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>数据下载</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">流量渠道</span>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">流量渠道下载</h1>
            <p className="text-sm text-muted-foreground mt-1">抓取店铺流量渠道数据，并生成按渠道分sheet分析结果</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={isRunning ? "default" : "secondary"} className="gap-1.5">
              {isRunning ? "运行中" : "待启动"}
            </Badge>
            <Button onClick={isRunning ? handleStop : handleStart} variant={isRunning ? "destructive" : "default"} className="gap-2">
              {isRunning ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
              {isRunning ? "停止" : "运行"}
            </Button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4 mb-6">
        <Card className="bg-gradient-to-br from-blue-50 to-white">
          <CardContent className="py-5">
            <div className="text-xs text-muted-foreground">最新日期数据</div>
            <div className="mt-2 text-2xl font-bold tracking-tight">UV {Math.round(stats.today.uv).toLocaleString()}</div>
            <div className="mt-1 text-xs text-muted-foreground">询盘 {Math.round(stats.today.ask).toLocaleString()} · TM {Math.round(stats.today.tm).toLocaleString()}</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-emerald-50 to-white">
          <CardContent className="py-5">
            <div className="text-xs text-muted-foreground">上周数据</div>
            <div className="mt-2 text-2xl font-bold tracking-tight">UV {Math.round(stats.week.uv).toLocaleString()}</div>
            <div className="mt-1 text-xs text-muted-foreground">询盘 {Math.round(stats.week.ask).toLocaleString()} · TM {Math.round(stats.week.tm).toLocaleString()}</div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-violet-50 to-white">
          <CardContent className="py-5">
            <div className="text-xs text-muted-foreground">上月数据</div>
            <div className="mt-2 text-2xl font-bold tracking-tight">UV {Math.round(stats.month.uv).toLocaleString()}</div>
            <div className="mt-1 text-xs text-muted-foreground">询盘 {Math.round(stats.month.ask).toLocaleString()} · TM {Math.round(stats.month.tm).toLocaleString()}</div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2 space-y-6">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-2">
                <CardTitle className="text-base">分析结果</CardTitle>
                <div className="text-xs text-muted-foreground">商机转化率低于 {(conversionWarnThreshold * 100).toFixed(0)}% 将高亮</div>
                <div className="flex items-center gap-2">
                  <select className="h-8 rounded border border-input bg-background px-2 text-xs" value={sheet} onChange={(e) => setSheet(e.target.value)}>
                    {sheets.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                  <Button size="sm" variant="outline" onClick={() => refreshOverview(sheet || undefined)} className="gap-1.5">
                    <RefreshCw className="w-3.5 h-3.5" /> 刷新
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="h-[360px] overflow-auto rounded-lg border border-border/50">
                <table className="w-full text-sm min-w-[760px]">
                  <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                    <tr className="border-b">
                      {(analysis.columns || []).length === 0 ? (
                        <th className="text-left py-3 px-3 text-xs text-muted-foreground">暂无列</th>
                      ) : analysis.columns.map((c) => (
                        <th key={c} className="text-left py-3 px-3 text-xs text-muted-foreground whitespace-nowrap">{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(analysis.rows || []).length === 0 ? (
                      <tr><td colSpan={Math.max((analysis.columns || []).length, 1)} className="py-8 text-center text-xs text-muted-foreground">暂无分析结果</td></tr>
                    ) : analysis.rows.map((r, i) => (
                      <tr key={`an-${i}`} className="border-b last:border-0 hover:bg-accent/30">
                        {analysis.columns.map((c) => {
                          const v = r?.[c];
                          const metricName = String(r?.["指标"] ?? r?.["指标名称"] ?? "").trim();
                          const rowIsPct = metricName === "商机转化率";
                          const isMetricCol = c === "指标" || c === "指标名称";
                          const isDeltaCol = c === "异动";
                          const rate = rowIsPct ? Number(analysisRateByCol[c]) : Number(v);
                          const warn = rowIsPct && !isMetricCol && !isDeltaCol && Number.isFinite(rate) && rate < conversionWarnThreshold;

                          const rendered = (() => {
                            if (!rowIsPct) return String(v ?? "");
                            if (isMetricCol) return String(v ?? "");
                            if (isDeltaCol) return "";
                            const calced = analysisRateByCol[c];
                            if (calced === undefined || calced === null || !Number.isFinite(calced)) return "";
                            return `${(calced * 100).toFixed(2)}%`;
                          })();

                          return (
                            <td key={c} className={`py-2.5 px-3 text-xs whitespace-nowrap ${warn ? "text-red-600 font-semibold" : ""}`}>
                              {rendered}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          {renderSummaryTable("最新日期数据", todayRows, todaySortKey, todaySortDir, (k) => {
            if (todaySortKey === k) setTodaySortDir((d) => d === "asc" ? "desc" : "asc");
            else {
              setTodaySortKey(k);
              setTodaySortDir("desc");
            }
          })}
          {renderSummaryTable("上周数据", weekRows, weekSortKey, weekSortDir, (k) => {
            if (weekSortKey === k) setWeekSortDir((d) => d === "asc" ? "desc" : "asc");
            else {
              setWeekSortKey(k);
              setWeekSortDir("desc");
            }
          })}
          {renderSummaryTable("上月数据", monthRows, monthSortKey, monthSortDir, (k) => {
            if (monthSortKey === k) setMonthSortDir((d) => d === "asc" ? "desc" : "asc");
            else {
              setMonthSortKey(k);
              setMonthSortDir("desc");
            }
          })}
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3"><CardTitle className="text-sm">文件配置模块</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">分析输出文件</Label>
                <Input value={outputFile} onChange={(e) => setOutputFile(e.target.value)} className="text-xs font-mono" />
              </div>
              <Separator />
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={saveConfig}>保存配置</Button>
                <Button size="sm" variant="ghost" onClick={loadConfig}>重载</Button>
                <Button size="sm" variant="ghost" onClick={() => refreshOverview(sheet || undefined)}>刷新数据</Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3"><CardTitle className="text-sm">运行日志</CardTitle></CardHeader>
            <CardContent>
              <div className="h-64 overflow-y-auto rounded-lg bg-gray-950 p-4">
                <div className="space-y-1 font-mono text-xs">
                  {logs.map((log, i) => <div key={i} className="text-gray-300">{log}</div>)}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
