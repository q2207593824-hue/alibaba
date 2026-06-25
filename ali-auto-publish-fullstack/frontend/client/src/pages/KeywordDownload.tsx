/**
 * KeywordDownload - 选词参谋关键词数据下载页面
 * 对应脚本: cs_选词参谋_店铺引流关键词下载.py
 * 功能: 关键词数据自动下载、数据汇总、异动分析
 */
import { useEffect, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import { configApi, dataApi, createLogSocket, membershipApi, hasApiCredentials } from "@/lib/api";
import {
  Search,
  Download,
  Pause,
  ChevronRight,
  FileSpreadsheet,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  ArrowUpDown,
} from "lucide-react";


export default function KeywordDownload() {
  const [activeTab, setActiveTab] = useState("keywords");
  const [isRunning, setIsRunning] = useState(false);
  const [logs, setLogs] = useState<string[]>([
    "[系统] 选词参谋数据下载模块已就绪",
  ]);

  const [downloadFolder, setDownloadFolder] = useState("");
  const [outputFolder, setOutputFolder] = useState("");
  const [keywordFiles, setKeywordFiles] = useState<any[]>([]);
  const [summaryData, setSummaryData] = useState<any>({ exposure: [], click: [] });
  const [anomalyData, setAnomalyData] = useState<any>({ exposure: [], click: [], index: [] });
  const parserRefreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshStatusLockRef = useRef(false);
  const lastUploadedSummarySigRef = useRef("");
  const memberAgentIdRef = useRef("");
  const refreshStatusTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const latestRequestSeqRef = useRef(0);
  const isRefreshingFilesRef = useRef(false);
  const isRefreshingSummaryRef = useRef(false);
  const isRefreshingAnomalyRef = useRef(false);
  const prevRunningRef = useRef(false);
  const lastStatusLogRef = useRef("");

  const taskType = "keyword_crawler";

  useEffect(() => {
    return () => {
      if (parserRefreshTimerRef.current) {
        clearTimeout(parserRefreshTimerRef.current);
      }
      if (refreshStatusTimerRef.current) {
        clearInterval(refreshStatusTimerRef.current);
      }
    };
  }, []);

  const normalizePath = (input: string) => input.trim().replace(/[/]+/g, "\\");

  const loadConfig = async () => {
    try {
      const cfg = (await configApi.getSection("keyword_download")) || {};
      const dl = cfg.download_folder || "";
      const out = cfg.output_folder || "";
      setDownloadFolder(dl);
      setOutputFolder(out);

      const requests: Promise<any>[] = [];
      if (dl) {
        requests.push(
          dataApi.getFiles(normalizePath(dl)).then((filesRes) => {
            const filesPayload = filesRes?.data ?? filesRes;
            return Array.isArray(filesPayload) ? filesPayload : filesPayload?.data || [];
          })
        );
      }
      if (out) {
        const outDir = normalizePath(out);
        requests.push(
          dataApi.getKeywordLatestSummary(outDir).then((summaryRes) => {
            const summaryPayload = summaryRes?.data ?? summaryRes;
            return summaryPayload?.data ?? summaryPayload;
          })
        );
        requests.push(
          dataApi.getKeywordLatestAnomaly(outDir).then((anomalyRes) => {
            const anomalyPayload = anomalyRes?.data ?? anomalyRes;
            return anomalyPayload?.data ?? anomalyPayload;
          })
        );
      }

      const [files, summary, anomaly] = await Promise.all(requests);
      if (files) setKeywordFiles(files);
      if (summary) {
        const normalized = summary || { exposure: [], click: [] };
        setSummaryData(normalized);
        void pushKeywordTelemetryIfUpdated(normalized);
      }
      if (anomaly) setAnomalyData(anomaly || { exposure: [], click: [], index: [] });
    } catch (e: any) {
      toast.error(e.message || "加载配置失败");
    }
  };

  const saveConfig = async () => {
    try {
      const current = (await configApi.getSection("keyword_download")) || {};
      await configApi.updateSection("keyword_download", {
        ...current,
        download_folder: downloadFolder,
        output_folder: outputFolder,
      });
      toast.success("关键词配置已保存");
      refreshKeywordFiles();
      refreshSummary();
      refreshAnomaly();
    } catch (e: any) {
      toast.error(e.message || "保存失败");
    }
  };

  const refreshKeywordFiles = async (silent = true) => {
    if (isRefreshingFilesRef.current) return;
    isRefreshingFilesRef.current = true;
    const requestSeq = ++latestRequestSeqRef.current;
    try {
      const dir = normalizePath(downloadFolder);
      if (!dir) {
        setKeywordFiles([]);
        return;
      }

      const res = await dataApi.getFiles(dir);
      if (requestSeq !== latestRequestSeqRef.current) return;

      const payload = res?.data ?? res;
      const next = Array.isArray(payload) ? payload : payload?.data || [];
      const ordered = (Array.isArray(next) ? next : []).slice().sort((a: any, b: any) => {
        const ta = Number(a?.modified || 0);
        const tb = Number(b?.modified || 0);
        if (ta !== tb) return tb - ta;

        const da = String(a?.name || "").match(/\d{4}-\d{2}-\d{2}/)?.[0] || "";
        const db = String(b?.name || "").match(/\d{4}-\d{2}-\d{2}/)?.[0] || "";
        return db.localeCompare(da);
      });

      setKeywordFiles(ordered);
      if (!silent) toast.success(`已刷新文件：${ordered.length} 条`);
    } catch {
      if (!silent) toast.error("刷新文件失败");
    } finally {
      isRefreshingFilesRef.current = false;
    }
  };

  const refreshAnomaly = async (silent = true) => {
    if (isRefreshingAnomalyRef.current) return;
    isRefreshingAnomalyRef.current = true;
    const requestSeq = ++latestRequestSeqRef.current;
    try {
      const dir = normalizePath(outputFolder);
      const res = await dataApi.getKeywordLatestAnomaly(dir);
      if (requestSeq !== latestRequestSeqRef.current) return;
      const payload = res?.data ?? res;
      const next = payload?.data ?? payload;
      setAnomalyData(next || { exposure: [], click: [], index: [] });
      if (!silent) {
        const count = (next.exposure?.length || 0) + (next.click?.length || 0) + (next.index?.length || 0);
        toast.success(`已刷新异动：${count} 条`);
      }
    } catch {
      if (!silent) toast.error("刷新异动失败");
    } finally {
      isRefreshingAnomalyRef.current = false;
    }
  };

  const refreshSummary = async (silent = true) => {
    if (isRefreshingSummaryRef.current) return;
    isRefreshingSummaryRef.current = true;
    const requestSeq = ++latestRequestSeqRef.current;
    try {
      const dir = normalizePath(outputFolder);
      const res = await dataApi.getKeywordLatestSummary(dir);
      if (requestSeq !== latestRequestSeqRef.current) return;
      const payload = res?.data ?? res;
      const next = payload?.data ?? payload;
      const normalized = next || { exposure: [], click: [] };
      setSummaryData(normalized);
      await pushKeywordTelemetryIfUpdated(normalized);
      if (!silent) {
        const count = (normalized.exposure?.length || 0) + (normalized.click?.length || 0);
        toast.success(`已刷新关键词：${count} 条`);
      }
    } catch {
      if (!silent) toast.error("刷新关键词失败");
    } finally {
      isRefreshingSummaryRef.current = false;
    }
  };

  const buildSummarySignature = (data: { exposure?: any[]; click?: any[] }) => {
    const exposure = Array.isArray(data?.exposure) ? data.exposure : [];
    const click = Array.isArray(data?.click) ? data.click : [];
    const clickMap = new Map<string, number>();
    click.forEach((x: any) => {
      const k = String(x?.keyword || "").trim();
      if (!k) return;
      clickMap.set(k, Number(x?.value || 0));
    });
    const parts = exposure
      .map((x: any) => {
        const k = String(x?.keyword || "").trim();
        if (!k) return "";
        const e = Number(x?.value || 0);
        const c = Number(clickMap.get(k) || 0);
        return `${k}:${e}:${c}`;
      })
      .filter(Boolean)
      .sort();
    return parts.join("|");
  };

  const buildTelemetryItems = (data: { exposure?: any[]; click?: any[] }) => {
    const exposureRows = Array.isArray(data?.exposure) ? data.exposure : [];
    const clickMap = new Map<string, number>();
    (Array.isArray(data?.click) ? data.click : []).forEach((x: any) => {
      const k = String(x?.keyword || "").trim();
      if (!k) return;
      clickMap.set(k, Number(x?.value || 0));
    });
    return exposureRows
      .slice(0, 200)
      .map((x: any) => {
        const keyword = String(x?.keyword || "").trim();
        const exposure = Number(x?.value || 0);
        const click = Number(clickMap.get(keyword) || 0);
        const ctr = exposure > 0 ? click / exposure : 0;
        return { keyword, exposure, click, ctr, keyword_index: 0, product_id: "" };
      })
      .filter((x: any) => !!x.keyword);
  };

  const resolveMemberAgentId = async () => {
    if (memberAgentIdRef.current) return memberAgentIdRef.current;
    try {
      const res: any = await membershipApi.me();
      const payload = res?.data ?? res;
      const data = payload?.data ?? payload;
      const username = String(data?.username || "").trim();
      if (username) {
        memberAgentIdRef.current = `member-${username}`;
        return memberAgentIdRef.current;
      }
    } catch {
      // ignore
    }
    const key = "client_device_uuid";
    let deviceId = "";
    try {
      deviceId = localStorage.getItem(key) || "";
      if (!deviceId) {
        deviceId =
          typeof crypto !== "undefined" && (crypto as any).randomUUID
            ? (crypto as any).randomUUID()
            : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
        localStorage.setItem(key, deviceId);
      }
    } catch {
      deviceId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }
    memberAgentIdRef.current = `agent-${deviceId}`;
    return memberAgentIdRef.current;
  };

  const pushKeywordTelemetryIfUpdated = async (data: { exposure?: any[]; click?: any[] }) => {
    try {
      if (!hasApiCredentials()) return;

      const sig = buildSummarySignature(data);
      if (!sig || sig === lastUploadedSummarySigRef.current) return;

      const items = buildTelemetryItems(data);
      if (!items.length) return;

      const agentId = await resolveMemberAgentId();
      const today = new Date().toISOString().slice(0, 10);

      await membershipApi.telemetryKeywords({
        agent_id: agentId,
        report_date: today,
        batch_no: `${today}-${sig.length}-${sig.slice(0, 32)}`,
        source: "keyword_summary",
        items,
      });

      lastUploadedSummarySigRef.current = sig;
    } catch {
      // 上报失败不影响本地功能
    }
  };

  const refreshStatus = async () => {
    if (refreshStatusLockRef.current) return;
    refreshStatusLockRef.current = true;
    try {
      const res = await dataApi.getDownloadStatus(taskType);
      const data = res?.data || res;
      const status = data?.data || data;
      const running = status?.status === "running" || status?.status === "stopping";
      setIsRunning(running);
      const raw = `${status?.status || ""}|${status?.current_step || ""}|${status?.error || ""}`;
      if (raw && raw !== lastStatusLogRef.current) {
        lastStatusLogRef.current = raw;
        const msg = status?.error
          ? `[任务] ${status?.current_step || "执行异常"} | 错误: ${status.error}`
          : `[任务] ${status?.current_step || (status?.status || "状态更新")}`;
        setLogs((prev) => [...prev, msg].slice(-500));
      }

      // 任务结束后自动刷新分析结果
      if (prevRunningRef.current && !running) {
        if (parserRefreshTimerRef.current) {
          clearTimeout(parserRefreshTimerRef.current);
        }
        parserRefreshTimerRef.current = setTimeout(() => {
          refreshKeywordFiles(false);
          refreshSummary(false);
          refreshAnomaly(false);
        }, 1000);
      }
      prevRunningRef.current = running;
    } catch {
      // ignore
    } finally {
      refreshStatusLockRef.current = false;
    }
  };

  const handleStart = async () => {
    try {
      if (!downloadFolder || !outputFolder) {
        toast.error("请先配置下载/输出目录");
        return;
      }
      setIsRunning(true);
      setLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] 开始关键词下载并分析...`]);
      await dataApi.startDownload({ task_type: taskType });
      toast.success("关键词下载并分析已启动");
      refreshStatus();
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

  const refreshCurrentTab = async (silent = false) => {
    if (activeTab === "keywords") {
      await refreshSummary(silent);
      return;
    }
    if (activeTab === "anomaly") {
      await refreshAnomaly(silent);
      return;
    }
    await refreshKeywordFiles(silent);
  };

  useEffect(() => {
    loadConfig();
  }, []);


  useEffect(() => {
    if (downloadFolder) refreshKeywordFiles();
  }, [downloadFolder]);

  useEffect(() => {
    if (outputFolder) {
      refreshSummary();
      refreshAnomaly();
    }
  }, [outputFolder]);

  useEffect(() => {
    refreshStatus();
    if (refreshStatusTimerRef.current) {
      clearInterval(refreshStatusTimerRef.current);
    }
    if (isRunning) {
      refreshStatusTimerRef.current = setInterval(() => {
        const isVisible = typeof document === "undefined" ? true : document.visibilityState === "visible";
        if (!isVisible) return;
        refreshStatus();
      }, 5000);
    }
    return () => {
      if (refreshStatusTimerRef.current) {
        clearInterval(refreshStatusTimerRef.current);
      }
    };
  }, [taskType, isRunning]);

  useEffect(() => {
    const ws = createLogSocket((data) => {
      if (!data) return;
      const payload = data.data || data;
      const moduleName = String(payload?.module || "");
      const msg = payload.message || payload.msg || payload.text;
      if (!msg) return;
      const text = String(msg);
      if (moduleName && moduleName !== "data_download") return;
      if (!text.includes("关键词") || text.includes("行业关键词")) return;
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

  return (
    <div className="p-8">
      <div className="mb-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>数据下载</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">关键词数据</span>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">选词参谋 - 关键词数据</h1>
            <p className="text-sm text-muted-foreground mt-1">接口下载店铺引流关键词，下载完成后自动汇总并生成异动分析</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={isRunning ? "default" : "secondary"} className="gap-1.5">
              {isRunning ? (
                <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
              ) : (
                <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
              )}
              {isRunning ? "运行中" : "待启动"}
            </Badge>
            <Button
              onClick={isRunning ? handleStop : handleStart}
              variant={isRunning ? "destructive" : "default"}
              className="gap-2"
            >
              {isRunning ? <Pause className="w-4 h-4" /> : <Download className="w-4 h-4" />}
              {isRunning ? "停止" : "开始下载"}
            </Button>
          </div>
        </div>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-1 gap-2 bg-transparent p-0 md:grid-cols-3">
          <TabsTrigger
            value="keywords"
            className="h-auto min-h-[46px] justify-start gap-2 rounded-lg border border-border/70 bg-card px-3 py-2 text-left data-[state=active]:border-primary/70 data-[state=active]:bg-primary/10 data-[state=active]:text-primary"
          >
            <Search className="w-3.5 h-3.5 shrink-0" />
            <span className="text-xs font-medium">店铺引流关键词</span>
          </TabsTrigger>
          <TabsTrigger
            value="anomaly"
            className="h-auto min-h-[46px] justify-start gap-2 rounded-lg border border-border/70 bg-card px-3 py-2 text-left data-[state=active]:border-primary/70 data-[state=active]:bg-primary/10 data-[state=active]:text-primary"
          >
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            <span className="text-xs font-medium">异动分析</span>
          </TabsTrigger>
          <TabsTrigger
            value="files"
            className="h-auto min-h-[46px] justify-start gap-2 rounded-lg border border-border/70 bg-card px-3 py-2 text-left data-[state=active]:border-primary/70 data-[state=active]:bg-primary/10 data-[state=active]:text-primary"
          >
            <FileSpreadsheet className="w-3.5 h-3.5 shrink-0" />
            <span className="text-xs font-medium">下载文件</span>
          </TabsTrigger>
        </TabsList>

        <Card className="mt-4">
          <CardContent className="py-3 space-y-3">
            <div className="text-xs text-muted-foreground">
              一次任务完成：接口拉取 → 生成周数据文件 → 自动汇总与异动分析
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">下载文件夹</Label>
                <Input value={downloadFolder} onChange={(e) => setDownloadFolder(e.target.value)} placeholder="D:\关键词数据" className="text-xs font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">输出文件夹</Label>
                <Input value={outputFolder} onChange={(e) => setOutputFolder(e.target.value)} placeholder="D:\关键词分析结果" className="text-xs font-mono" />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2">
              <Button size="sm" variant="outline" onClick={saveConfig}>保存配置</Button>
              <Button size="sm" variant="default" onClick={() => refreshCurrentTab(false)}>刷新当前页</Button>
            </div>
          </CardContent>
        </Card>

        {/* Keywords Data */}
        <TabsContent value="keywords" className="mt-6">
          <div className="grid grid-cols-2 gap-4">
            {[
              { key: "exposure", title: "曝光量", thresholdText: "> 40" },
              { key: "click", title: "点击量", thresholdText: "> 10" },
            ].map((section) => {
              const rows = summaryData?.[section.key] || [];
              return (
                <Card key={section.key}>
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <CardTitle className="text-base">{section.title}</CardTitle>
                      <Badge variant="outline" className="text-[10px]">阈值 {section.thresholdText}</Badge>
                    </div>
                  </CardHeader>
                  <CardContent>
                    <div className="h-72 overflow-y-auto rounded-lg border border-border/50">
                      {rows.length === 0 ? (
                        <div className="text-xs text-muted-foreground p-3">暂无关键词数据</div>
                      ) : (
                        <div className="divide-y">
                          {rows.map((item: any, idx: number) => (
                            <div key={`${section.key}-${idx}`} className="px-3 py-2 text-xs flex items-center justify-between">
                              <span className="font-mono truncate mr-2" title={item.keyword}>{item.keyword}</span>
                              <span className="font-semibold">{Number(item.value || 0).toLocaleString()}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </TabsContent>

        {/* Anomaly Analysis */}
        <TabsContent value="anomaly" className="mt-6">
          <div className="grid grid-cols-3 gap-4">
            {[
              { key: "exposure", title: "曝光异动", color: "border-l-red-500", icon: TrendingUp },
              { key: "click", title: "点击量异动", color: "border-l-amber-500", icon: TrendingDown },
              { key: "index", title: "关键词指数异动", color: "border-l-blue-500", icon: ArrowUpDown },
            ].map((section) => {
              const rows = [...(anomalyData?.[section.key] || [])].sort(
                (a: any, b: any) => Math.abs(Number(b?.value || 0)) - Math.abs(Number(a?.value || 0))
              );
              return (
                <Card key={section.key} className={`border-l-4 ${section.color}`}>
                  <CardHeader className="pb-2">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <section.icon className="w-4 h-4" />
                      {section.title}
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="h-72 overflow-y-auto rounded-lg border border-border/50">
                      {rows.length === 0 ? (
                        <div className="text-xs text-muted-foreground p-3">暂无最新异动数据</div>
                      ) : (
                        <div className="divide-y">
                          {rows.map((item: any, idx: number) => (
                            <div key={`${section.key}-${idx}`} className="px-3 py-2 text-xs flex items-center justify-between">
                              <span className="font-mono truncate mr-2" title={item.keyword}>{item.keyword}</span>
                              <span className="font-semibold">{Number(item.value || 0).toLocaleString()}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </TabsContent>

        {/* Downloaded Files */}
        <TabsContent value="files" className="mt-6">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">已下载文件</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-56 overflow-y-auto rounded-lg border border-border/50">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                    <tr className="border-b">
                      <th className="text-left py-3 px-4 font-medium text-xs text-muted-foreground">文件名</th>
                      <th className="text-left py-3 px-4 font-medium text-xs text-muted-foreground">日期</th>
                      <th className="text-left py-3 px-4 font-medium text-xs text-muted-foreground">大小</th>
                      <th className="text-left py-3 px-4 font-medium text-xs text-muted-foreground">状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {keywordFiles.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="py-6 text-center text-xs text-muted-foreground">暂无文件</td>
                      </tr>
                    ) : (
                      keywordFiles.map((file) => (
                        <tr key={file.path || file.name} className="border-b last:border-0 hover:bg-accent/30">
                          <td className="py-3 px-4 text-xs font-mono">{file.name}</td>
                          <td className="py-3 px-4 text-xs text-muted-foreground">
                            {file.name?.match(/\d{4}-\d{2}-\d{2}/)?.[0] || "--"}
                          </td>
                          <td className="py-3 px-4 text-xs text-muted-foreground">
                            {file.size_bytes ? `${Math.round(file.size_bytes / 1024)}KB` : "--"}
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
        </TabsContent>
      </Tabs>

      {/* Logs */}
      <Card className="mt-6">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">运行日志</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-40 overflow-y-auto rounded-lg bg-gray-950 p-4">
            <div className="space-y-1 font-mono text-xs">
              {logs.map((log, i) => (
                <div key={i} className="text-gray-300">{log}</div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
