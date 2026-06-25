import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Activity, Database, Loader2, RefreshCw, Sparkles, Terminal } from "lucide-react";

import { Button } from "@/components/ui/button";
import { analysisApi, configApi, createLogSocket, dataApi, taskApi, uploadApi } from "@/lib/api";

const formatTime = (value: any) => {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
};

export default function Home() {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string>("");
  const [config, setConfig] = useState<any>(null);
  const [uploadStatus, setUploadStatus] = useState<any>(null);
  const [taskList, setTaskList] = useState<any[]>([]);
  const [analysisOverview, setAnalysisOverview] = useState<any>(null);
  const [downloadStatus, setDownloadStatus] = useState<any>(null);
  const [logs, setLogs] = useState<string[]>([]);

  const summaryCards = useMemo(() => {
    const uploadRunning = uploadStatus?.running || uploadStatus?.is_running || uploadStatus?.status || "unknown";
    return [
      { label: "当前发品状态", value: String(uploadRunning) },
      { label: "任务数量", value: String(taskList.length) },
      { label: "分析概览", value: analysisOverview?.status || analysisOverview?.message || "未加载" },
      { label: "下载状态", value: downloadStatus ? "已加载" : "未加载" },
    ];
  }, [uploadStatus, taskList.length, analysisOverview, downloadStatus]);

  const loadHome = async () => {
    setError("");
    const [cfg, upload, tasks, overview, downloads] = await Promise.allSettled([
      configApi.get(),
      uploadApi.getStatus(),
      taskApi.list(),
      analysisApi.getOverview(),
      dataApi.getAllDownloadStatus(),
    ]);

    if (cfg.status === "fulfilled") setConfig(cfg.value);
    if (upload.status === "fulfilled") setUploadStatus(upload.value?.data ?? upload.value);
    if (tasks.status === "fulfilled") setTaskList(tasks.value?.data ?? tasks.value ?? []);
    if (overview.status === "fulfilled") setAnalysisOverview(overview.value?.data ?? overview.value);
    if (downloads.status === "fulfilled") setDownloadStatus(downloads.value?.data ?? downloads.value);
  };

  useEffect(() => {
    let ws: WebSocket | null = null;
    let alive = true;

    (async () => {
      try {
        setLoading(true);
        await loadHome();
        if (!alive) return;
        ws = createLogSocket((data) => {
          const entry = data?.data || data?.message || data;
          const line = typeof entry === "string"
            ? entry
            : `[${entry?.timestamp || ""}] [${entry?.level || "INFO"}] ${entry?.message || JSON.stringify(entry || {})}`;
          setLogs((prev) => [...prev.slice(-49), line]);
        });
      } catch (e: any) {
        setError(e?.message || "首页数据加载失败");
      } finally {
        if (alive) setLoading(false);
      }
    })();

    return () => {
      alive = false;
      ws?.close();
    };
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await loadHome();
    } catch (e: any) {
      setError(e?.message || "首页数据加载失败");
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-7xl p-6 space-y-6">
        <div className="flex items-center justify-between gap-4 rounded-2xl border bg-card p-6 shadow-sm">
          <div>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Sparkles className="h-4 w-4" />
              首页仪表盘
            </div>
            <h1 className="mt-2 text-2xl font-semibold">进入 Home 即自动加载数据</h1>
            <p className="mt-1 text-sm text-muted-foreground">当前页面会自动拉取配置、任务状态、分析概览和实时日志。</p>
          </div>
          <Button onClick={handleRefresh} disabled={refreshing}>
            {refreshing ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
            刷新数据
          </Button>
        </div>

        {error ? (
          <div className="flex items-center gap-2 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
            <AlertCircle className="h-4 w-4" />
            {error}
          </div>
        ) : null}

        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {summaryCards.map((card) => (
            <div key={card.label} className="rounded-2xl border bg-card p-5 shadow-sm">
              <div className="text-sm text-muted-foreground">{card.label}</div>
              <div className="mt-3 text-2xl font-semibold">{card.value}</div>
            </div>
          ))}
        </div>

        <div className="grid gap-6 xl:grid-cols-2">
          <div className="rounded-2xl border bg-card p-5 shadow-sm">
            <div className="flex items-center gap-2 text-lg font-medium">
              <Database className="h-5 w-5" />
              配置与状态
            </div>
            {loading ? <div className="mt-4 text-sm text-muted-foreground">正在加载...</div> : null}
            <div className="mt-4 space-y-3 text-sm">
              <div>店铺/配置：{config?.shop_name || config?.shop_url || config?.name || "暂无"}</div>
              <div>发品状态：{uploadStatus?.status || uploadStatus?.running || "暂无"}</div>
              <div>最近更新时间：{formatTime(uploadStatus?.updated_at || analysisOverview?.updated_at || config?.updated_at)}</div>
            </div>
          </div>

          <div className="rounded-2xl border bg-card p-5 shadow-sm">
            <div className="flex items-center gap-2 text-lg font-medium">
              <Terminal className="h-5 w-5" />
              实时日志
            </div>
            <div className="mt-4 h-[320px] overflow-auto rounded-xl bg-muted/30 p-4 text-sm">
              {logs.length ? (
                <div className="space-y-2 font-mono leading-6">
                  {logs.map((line, idx) => (
                    <div key={`${idx}-${line}`} className="break-all">{line}</div>
                  ))}
                </div>
              ) : (
                <div className="text-muted-foreground">暂无日志，等待任务运行或接口推送。</div>
              )}
            </div>
          </div>
        </div>

        <div className="rounded-2xl border bg-card p-5 shadow-sm">
          <div className="flex items-center gap-2 text-lg font-medium">
            <Activity className="h-5 w-5" />
            最近任务
          </div>
          <div className="mt-4 overflow-hidden rounded-xl border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left">
                <tr>
                  <th className="px-4 py-3 font-medium">任务 ID</th>
                  <th className="px-4 py-3 font-medium">名称</th>
                  <th className="px-4 py-3 font-medium">状态</th>
                </tr>
              </thead>
              <tbody>
                {taskList.slice(0, 5).map((task: any, idx: number) => (
                  <tr key={task.id || task.task_id || idx} className="border-t">
                    <td className="px-4 py-3">{task.id || task.task_id || `#${idx + 1}`}</td>
                    <td className="px-4 py-3">{task.name || task.type || task.title || "未命名任务"}</td>
                    <td className="px-4 py-3">{task.status || task.state || "未知"}</td>
                  </tr>
                ))}
                {!taskList.length ? (
                  <tr>
                    <td className="px-4 py-3 text-muted-foreground" colSpan={3}>暂无任务数据</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
