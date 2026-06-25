/**
 * VideoBind - 新品绑定视频管理页面
 * 对接后端: /api/video-bind/*
 */
import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { toast } from "sonner";
import { useLogStream, useTaskStatus } from "@/hooks/useApi";
import { videoBindApi } from "@/lib/api";
import {
  Play,
  Pause,
  Square,
  RotateCcw,
  Settings,
  FileText,
  AlertCircle,
  ChevronRight,
} from "lucide-react";

const extractRows = (value: any): any[] => {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  if (Array.isArray(value.data)) return value.data;
  if (Array.isArray(value.rows)) return value.rows;
  if (Array.isArray(value.table)) return value.table;
  if (Array.isArray(value.items)) return value.items;
  if (Array.isArray(value.result)) return value.result;
  if (value.data) return extractRows(value.data);
  if (value.rows) return extractRows(value.rows);
  if (value.table) return extractRows(value.table);
  if (value.items) return extractRows(value.items);
  if (value.result) return extractRows(value.result);
  return [];
};

const parseDate = (value: any) => {
  const raw = String(value ?? "").trim().replace(/\.0+$/, "");
  if (!raw) return null;
  let clean = raw.replace(/[^0-9]/g, "");
  // 兼容 Excel 把 yyMMdd 读成 260424.0 这类场景，清洗后可能变成 7 位
  if (clean.length === 7 && clean.endsWith("0")) {
    clean = clean.slice(0, 6);
  }

  // 纯数字优先按 yyMMdd / yyyyMMdd 解析，避免被 Date() 误判成年份
  if (clean.length === 6) {
    const yy = Number(clean.slice(0, 2));
    const mm = Number(clean.slice(2, 4));
    const dd = Number(clean.slice(4, 6));
    const date = new Date(2000 + yy, mm - 1, dd);
    if (!Number.isNaN(date.getTime())) return date;
  }
  if (clean.length === 8) {
    const yyyy = Number(clean.slice(0, 4));
    const mm = Number(clean.slice(4, 6));
    const dd = Number(clean.slice(6, 8));
    const date = new Date(yyyy, mm - 1, dd);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  // Excel 序列号日期（例如 45678）
  if (/^\d+(\.\d+)?$/.test(raw)) {
    const serial = Number(raw);
    if (Number.isFinite(serial) && serial > 20000 && serial < 100000) {
      const base = new Date(Date.UTC(1899, 11, 30));
      const date = new Date(base.getTime() + Math.floor(serial) * 24 * 60 * 60 * 1000);
      if (!Number.isNaN(date.getTime())) {
        return new Date(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
      }
    }
  }

  // 含分隔符/时间格式再走原生 Date 解析
  if (/[^\d]/.test(raw)) {
    const direct = new Date(raw.replace(/\./g, "-").replace("T", " "));
    if (!Number.isNaN(direct.getTime())) {
      return new Date(direct.getFullYear(), direct.getMonth(), direct.getDate());
    }
  }
  return null;
};

const pickDateRaw = (row: Record<string, any>) => {
  const keys = Object.keys(row || {});
  const exactCandidates = ["发品日期", "日期", "date", "日期时间"];
  for (const c of exactCandidates) {
    if (Object.prototype.hasOwnProperty.call(row || {}, c)) {
      const v = row[c];
      if (String(v ?? "").trim()) return v;
    }
  }

  // 再做模糊匹配：仅返回非空值，避免匹配到空列导致整行误判
  for (const k of keys) {
    const nk = String(k || "").trim().toLowerCase();
    if (nk.includes("发品日期") || nk === "date" || nk === "日期" || nk.includes("日期时间")) {
      const v = row[k];
      if (String(v ?? "").trim()) return v;
    }
  }
  return row?.["发品日期"] ?? row?.["日期"] ?? row?.["date"] ?? row?.["日期时间"];
};

const pickParseableDateRaw = (row: Record<string, any>) => {
  const keys = Object.keys(row || {});
  const values: any[] = [];

  // 精确候选优先
  for (const k of ["发品日期", "日期", "date", "日期时间"]) {
    if (Object.prototype.hasOwnProperty.call(row || {}, k)) values.push(row[k]);
  }

  // 模糊候选兜底
  for (const k of keys) {
    const nk = String(k || "").trim().toLowerCase();
    if (nk.includes("发品日期") || nk === "date" || nk === "日期" || nk.includes("日期时间")) {
      values.push(row[k]);
    }
  }

  for (const v of values) {
    if (parseDate(v)) return v;
  }
  return pickDateRaw(row);
};

const isWithin30Days = (value: any) => {
  const date = parseDate(value);
  if (!date) return false;
  const diffDays = (Date.now() - date.getTime()) / (1000 * 60 * 60 * 24);
  return diffDays >= 0 && diffDays <= 30;
};

export default function VideoBind() {
  const [isRunning, setIsRunning] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [videoPerProductLimit, setVideoPerProductLimit] = useState(10);
  const [maxLinkedCount, setMaxLinkedCount] = useState(18);
  const [newLinkRawRows, setNewLinkRawRows] = useState<any[]>([]);
  const [newLinkLoading, setNewLinkLoading] = useState(false);
  const [newLinkSource, setNewLinkSource] = useState("");
  const [newLinkHint, setNewLinkHint] = useState("");

  const { logs, clearLogs } = useLogStream();

  const taskStatus = useTaskStatus(
    () => videoBindApi.getStatus(),
    true
  );

  const backendStatus = taskStatus?.status || "idle";
  const uiRunning = backendStatus === "running" || backendStatus === "stopping";
  const uiPaused = backendStatus === "paused";

  const activeStep = (() => {
    if (!taskStatus) return 0;
    if (["idle", "completed", "failed"].includes(backendStatus)) return 0;

    const step = taskStatus.current_step || "";
    if (step.includes("登录")) return 1;
    if (step.includes("新发链接")) return 2;
    if (step.includes("匹配")) return 3;
    if (step.includes("绑定")) return 4;
    if (step.includes("完成")) return 5;
    return taskStatus.progress > 0 ? 3 : 1;
  })();

  const loadNewLinks = useCallback(async () => {
    setNewLinkLoading(true);
    try {
      const res = await videoBindApi.getNewLinksPreview();
      const payload = res?.data ?? res;
      const source = String(payload?.source || "").trim();
      const sheetName = String(payload?.sheet_name || "").trim();
      const idCol = String(payload?.id_col || "新发链接");
      const typeCol = String(payload?.type_col || "类型");
      const bindCol = String(payload?.bind_col || "绑定视频");
      setNewLinkSource(source && sheetName ? `${source} / ${sheetName}` : source || sheetName || "-");

      const allRows = extractRows(payload);
      const rowsIn30Days = allRows.filter((row) => isWithin30Days(pickParseableDateRaw(row)));
      const rowsForDisplay = rowsIn30Days.length > 0 ? rowsIn30Days : allRows;
      setNewLinkHint(
        rowsIn30Days.length > 0
          ? ""
          : (allRows.length > 0 ? "未识别到可用的发品日期，已回退展示源表数据（未做30天过滤）" : "")
      );

      const mappedRows = rowsForDisplay.map((row) => ({
        ...row,
        __id: String(row?.[idCol] ?? row?.["新发链接"] ?? row?.["链接"] ?? row?.["product_id"] ?? row?.["产品ID"] ?? row?.["ID"] ?? ""),
        __type: String(row?.[typeCol] ?? row?.["类型"] ?? row?.["type"] ?? row?.["分类"] ?? ""),
        __bind: String(row?.[bindCol] ?? row?.["绑定视频"] ?? row?.["video"] ?? row?.["视频"] ?? row?.["主图"] ?? ""),
      }));
      setNewLinkRawRows(mappedRows);
    } catch {
      setNewLinkRawRows([]);
      setNewLinkHint("");
    } finally {
      setNewLinkLoading(false);
    }
  }, []);

  useEffect(() => {
    loadNewLinks();
  }, [loadNewLinks]);

  useEffect(() => {
    if (taskStatus?.status === "completed" || taskStatus?.status === "failed") {
      setIsRunning(false);
      setIsPaused(false);
      if (taskStatus.status === "completed") {
        toast.success("新品绑定视频任务已完成");
      } else {
        toast.error(`任务失败: ${taskStatus.error || "未知错误"}`);
      }
    }
    if (taskStatus?.status === "idle") {
      setIsRunning(false);
      setIsPaused(false);
    }
  }, [taskStatus?.status]);

  const handleStart = useCallback(async () => {
    try {
      await videoBindApi.start({
        video_per_product_limit: videoPerProductLimit,
        max_linked_count: maxLinkedCount,
      });
      setIsRunning(true);
      setIsPaused(false);
      toast.success("新品绑定视频任务已启动");
    } catch (e: any) {
      toast.error(e.message || "启动失败");
    }
  }, [videoPerProductLimit, maxLinkedCount]);

  const handleStop = useCallback(async () => {
    try {
      await videoBindApi.stop();
      setIsRunning(false);
      setIsPaused(false);
      toast.info("任务已停止");
    } catch (e: any) {
      toast.error(e.message || "停止失败");
    }
  }, []);

  const handlePause = useCallback(async () => {
    try {
      if (uiPaused) {
        await videoBindApi.resume();
        setIsPaused(false);
        toast.info("任务已恢复");
      } else {
        await videoBindApi.pause();
        setIsPaused(true);
        toast.info("任务已暂停");
      }
    } catch (e: any) {
      toast.error(e.message || "操作失败");
    }
  }, [uiPaused]);

  return (
    <div className="p-8">
      <div className="mb-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>产品上传</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">新品绑定视频</span>
        </div>
        <h1 className="text-2xl font-bold text-foreground">新品绑定视频</h1>
        <p className="text-sm text-muted-foreground mt-1">
          自动读取新发链接监控表，匹配视频并批量绑定产品主图
        </p>
      </div>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2 space-y-6">
          <Card>
            <CardContent className="py-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {!uiRunning && !uiPaused ? (
                    <Button onClick={handleStart} className="gap-2">
                      <Play className="w-4 h-4" />
                      开始绑定
                    </Button>
                  ) : (
                    <>
                      <Button onClick={handlePause} variant="outline" className="gap-2">
                        {uiPaused ? <Play className="w-4 h-4" /> : <Pause className="w-4 h-4" />}
                        {uiPaused ? "恢复" : "暂停"}
                      </Button>
                      <Button onClick={handleStop} variant="destructive" className="gap-2">
                        <Square className="w-4 h-4" />
                        停止
                      </Button>
                    </>
                  )}
                  <Button variant="outline" onClick={clearLogs} className="gap-2">
                    <RotateCcw className="w-4 h-4" />
                    清空日志
                  </Button>
                </div>
                <div className="flex items-center gap-4">
                  <Badge variant={uiRunning ? (uiPaused ? "secondary" : "default") : "secondary"} className="gap-1.5">
                    {uiRunning ? (
                      uiPaused ? (
                        <span className="w-1.5 h-1.5 rounded-full bg-yellow-400" />
                      ) : (
                        <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                      )
                    ) : (
                      <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
                    )}
                    {uiRunning ? (uiPaused ? "已暂停" : "运行中") : "待启动"}
                  </Badge>
                  {taskStatus && (
                    <span className="text-sm text-muted-foreground">
                      {taskStatus.progress ?? 0}/{taskStatus.total ?? 0} 条
                    </span>
                  )}
                </div>
              </div>
              {taskStatus?.current_step && (
                <div className="mt-3 text-xs text-muted-foreground bg-muted/50 rounded-md px-3 py-2">
                  当前: {taskStatus.current_step}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">新品视频绑定</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="rounded-lg border overflow-hidden">
                <div className="flex items-center justify-between px-4 py-3 border-b bg-muted/30">
                  <div className="space-y-0.5">
                    <div className="text-sm font-medium">综合数据分析 / 文件目录配置 / 新发链接文件</div>
                    <div className="text-xs text-muted-foreground">{newLinkSource || "正在读取配置..."}</div>
                  </div>
                  <Button variant="outline" size="sm" onClick={loadNewLinks} className="gap-2">
                    <RotateCcw className="w-4 h-4" />
                    刷新
                  </Button>
                </div>
                <div className="h-[440px] overflow-auto">
                  {newLinkHint ? (
                    <div className="px-4 py-2 text-xs text-amber-700 bg-amber-50 border-b border-amber-200">
                      {newLinkHint}
                    </div>
                  ) : null}
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 z-10 bg-muted/95 text-muted-foreground shadow-[0_1px_0_rgba(0,0,0,0.06)]">
                      <tr>
                        <th className="text-left px-4 py-3 font-medium whitespace-nowrap">产品ID</th>
                        <th className="text-left px-4 py-3 font-medium whitespace-nowrap">发品日期</th>
                        <th className="text-left px-4 py-3 font-medium whitespace-nowrap">类型</th>
                        <th className="text-left px-4 py-3 font-medium whitespace-nowrap">绑定视频</th>
                      </tr>
                    </thead>
                    <tbody>
                      {newLinkLoading ? (
                        <tr>
                          <td colSpan={4} className="px-4 py-10 text-center text-muted-foreground">加载中...</td>
                        </tr>
                      ) : newLinkRawRows.length === 0 ? (
                        <tr>
                          <td colSpan={4} className="px-4 py-10 text-center text-muted-foreground">暂无30天内的新发链接数据</td>
                        </tr>
                      ) : (
                        newLinkRawRows.map((row, idx) => (
                          <tr key={idx} className="border-t align-top">
                            <td className="px-4 py-3 whitespace-nowrap">{String(row?.__id ?? row?.["新发链接"] ?? row?.["链接"] ?? row?.["product_id"] ?? row?.["产品ID"] ?? row?.["ID"] ?? "")}</td>
                            <td className="px-4 py-3 whitespace-nowrap">{String(row?.["发品日期"] ?? row?.["日期"] ?? row?.["date"] ?? row?.["日期时间"] ?? "")}</td>
                            <td className="px-4 py-3 whitespace-nowrap">{String(row?.__type ?? row?.["类型"] ?? row?.["type"] ?? row?.["分类"] ?? "")}</td>
                            <td className="px-4 py-3 whitespace-pre-wrap break-words">{String(row?.__bind ?? row?.["绑定视频"] ?? row?.["video"] ?? row?.["视频"] ?? row?.["主图"] ?? "").split(/\r?\n/)[0]}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <FileText className="w-4 h-4" />
                运行日志
                <Badge variant="secondary" className="ml-2 text-[10px]">{logs.length} 条</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ScrollArea className="h-48 rounded-lg bg-gray-950 p-4">
                <div className="space-y-1 font-mono text-xs">
                  {logs.length === 0 ? (
                    <div className="text-gray-500">[系统] 等待启动...</div>
                  ) : (
                    logs.map((log, i) => (
                      <div
                        key={i}
                        className={`${
                          log.includes("ERROR") || log.includes("失败")
                            ? "text-red-400"
                            : log.includes("完成") || log.includes("成功")
                            ? "text-emerald-400"
                            : log.includes("WARNING")
                            ? "text-yellow-400"
                            : "text-gray-300"
                        }`}
                      >
                        {log}
                      </div>
                    ))
                  )}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <Settings className="w-4 h-4" />
                快速配置
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">每个视频最多绑定产品数</Label>
                <Input
                  type="number"
                  value={videoPerProductLimit}
                  onChange={(e) => setVideoPerProductLimit(parseInt(e.target.value) || 10)}
                  className="text-sm"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">允许的最大关联主图数</Label>
                <Input
                  type="number"
                  value={maxLinkedCount}
                  onChange={(e) => setMaxLinkedCount(parseInt(e.target.value) || 18)}
                  className="text-sm"
                />
              </div>
              <Separator />
              <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                读取：综合数据分析下文件目录配置的新发链接文件
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <AlertCircle className="w-4 h-4" />
                说明
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3 text-xs text-muted-foreground">
                <div className="flex items-start gap-2">
                  <AlertCircle className="w-3.5 h-3.5 mt-0.5 text-amber-500 shrink-0" />
                  <span>只显示发品日期在 30 天以内的数据，超过 30 天的产品不会展示。</span>
                </div>
                <div className="flex items-start gap-2">
                  <AlertCircle className="w-3.5 h-3.5 mt-0.5 text-amber-500 shrink-0" />
                  <span>绑定视频仅展示第一行的数据内容。</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
