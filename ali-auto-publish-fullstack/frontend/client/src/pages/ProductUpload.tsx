/**
 * ProductUpload - 自动发品管理页面
 * 对接后端: /api/upload/*
 * 功能: 产品上传流程管理、实时日志、任务控制
 *
 * 【如何修改】
 * - 修改流程步骤展示 → 修改 uploadSteps 数组
 * - 修改配置面板 → 修改右侧 Config Panel 部分
 * - 修改日志展示 → 修改 Logs Card 部分
 */
import { useState, useEffect, useCallback, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { toast } from "sonner";
import { analysisApi, configApi, uploadApi } from "@/lib/api";
import { useLogStream, useTaskStatus } from "@/hooks/useApi";
import {
  Play,
  Pause,
  Square,
  RotateCcw,
  Upload,
  Settings,
  FileText,
  ImageIcon,
  DollarSign,
  Tag,
  Globe,
  CheckCircle2,
  AlertCircle,
  Clock,
  Layers,
  ChevronRight,
} from "lucide-react";

type NewProductRow = {
  product_id: string;
  publish_date: string;
  type: string;
  publish_days: number | null;
};

const uploadSteps = [
  { id: 1, name: "登录验证", desc: "Cookie登录或手动登录阿里巴巴国际站", icon: Globe },
  { id: 2, name: "读取数据源", desc: "从Excel读取产品数据和配置信息", icon: FileText },
  { id: 3, name: "属性融合", desc: "合并产品属性、处理自定义属性映射", icon: Layers },
  { id: 4, name: "图片上传", desc: "上传首图、详情图、SKU图片", icon: ImageIcon },
  { id: 5, name: "价格设置", desc: "配置阶梯价格和FOB价格", icon: DollarSign },
  { id: 6, name: "填写属性", desc: "自动填写产品属性和规格", icon: Tag },
  { id: 7, name: "发布产品", desc: "提交产品信息并发布上线", icon: Upload },
];

export default function ProductUpload() {
  const [isRunning, setIsRunning] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [maxProductsInput, setMaxProductsInput] = useState("10");
  const [uploadDelay, setUploadDelay] = useState(15);
  const [enableShowcase, setEnableShowcase] = useState(false);
  const [enableP4P, setEnableP4P] = useState(false);
  const [publishMode, setPublishMode] = useState<"immediate" | "scheduled" | "daily_scheduled">("immediate");
  const [scheduledTime, setScheduledTime] = useState("22:00");

  const [newProducts, setNewProducts] = useState<NewProductRow[]>([]);
  const [runtimeLogs, setRuntimeLogs] = useState<string[]>(["[系统] 自动发品模块已就绪"]);
  const [configLoaded, setConfigLoaded] = useState(false);
  const [configLoading, setConfigLoading] = useState(false);
  const saveTimerRef = useRef<number | null>(null);
  const lastStatusLogRef = useRef("");
  const titleHealthWarnedRef = useRef(false);
  const streamLogCountRef = useRef(0);
  const parsedMaxProducts = Number.parseInt(maxProductsInput, 10);
  const maxProducts = Number.isFinite(parsedMaxProducts) && parsedMaxProducts > 0 ? parsedMaxProducts : undefined;

  // 实时日志
  const { logs, clearLogs } = useLogStream();

  const appendRuntimeLog = useCallback((text: string) => {
    if (!text) return;
    setRuntimeLogs((prev) => [...prev, text].slice(-500));
  }, []);

  // 任务状态轮询：始终开启，确保刷新页面后也能从后端恢复真实状态
  const taskStatus = useTaskStatus(
    () => uploadApi.getStatus(),
    true
  );

  // 根据任务状态推断当前步骤
  const activeStep = (() => {
    if (!taskStatus) return 0;
    const step = taskStatus.current_step || "";
    if (step.includes("登录")) return 1;
    if (step.includes("加载") || step.includes("扫描")) return 2;
    if (step.includes("属性")) return 3;
    if (step.includes("图片")) return 4;
    if (step.includes("价格")) return 5;
    if (step.includes("填写")) return 6;
    if (step.includes("发布") || step.includes("提交")) return 7;
    if (step.includes("完成")) return 8;
    return taskStatus.progress > 0 ? 3 : 1;
  })();

  // 监听任务状态，保证刷新后按钮状态与后端一致
  useEffect(() => {
    const status = String(taskStatus?.status || "idle");
    const runningNow = status === "running" || status === "paused" || status === "stopping";

    setIsRunning(runningNow);
    setIsPaused(status === "paused");

    if (status === "completed" || status === "failed") {
      if (status === "completed") {
        toast.success("发品任务已完成");
      } else {
        toast.error(`任务失败: ${taskStatus?.error || "未知错误"}`);
      }
    }
  }, [taskStatus?.status, taskStatus?.error]);

  // WebSocket 日志（有就用）
  useEffect(() => {
    if (!Array.isArray(logs)) return;
    const start = streamLogCountRef.current;
    if (logs.length <= start) return;
    const added = logs.slice(start);
    streamLogCountRef.current = logs.length;
    for (const line of added) {
      appendRuntimeLog(String(line || ""));
    }
  }, [logs, appendRuntimeLog]);

  // 任务状态日志兜底（WS 403/无消息时也能看到过程）
  useEffect(() => {
    if (!taskStatus) return;
    const status = String(taskStatus?.status || "idle");
    const step = String(taskStatus?.current_step || "");
    const err = String(taskStatus?.error || "");
    const raw = `${status}|${step}|${err}`;
    if (raw === lastStatusLogRef.current) return;
    lastStatusLogRef.current = raw;

    // 过滤纯空闲噪音
    if (status === "idle" && !step && !err) return;

    const msg = err
      ? `[任务] ${step || "执行异常"} | 错误: ${err}`
      : `[任务] ${step || status}`;
    appendRuntimeLog(msg);
  }, [taskStatus, appendRuntimeLog]);

  // 标题 Excel 配置异常时提示（避免静默导致“无可发品”）
  useEffect(() => {
    const health = taskStatus?.title_excel_health;
    if (!health || health.ok || titleHealthWarnedRef.current) return;
    titleHealthWarnedRef.current = true;
    const msg = String(health.message || "标题 Excel 配置异常");
    toast.error(msg);
    appendRuntimeLog(`[配置] ${msg}`);
  }, [taskStatus?.title_excel_health, appendRuntimeLog]);

  // 加载并回填快速配置
  const loadQuickConfig = useCallback(async () => {
    setConfigLoading(true);
    try {
      const sections = await configApi.getSections(["upload", "image_norm", "payment"]);
      const upload = sections.upload || {};
      const imageNorm = sections.image_norm || {};
      const payment = sections.payment || {};

      const configMaxProducts = Number(upload?.max_products_per_run ?? 10);
      setMaxProductsInput(Number.isFinite(configMaxProducts) && configMaxProducts > 0 ? String(configMaxProducts) : "");
      setUploadDelay(Number(upload?.upload_interval_seconds || 15));
      setEnableShowcase(!!imageNorm?.enable_showcase);
      setEnableP4P(!!payment?.enable_p4p);

      const scheduleMode = String(upload?.schedule_mode || "immediate");
      if (scheduleMode === "scheduled" || scheduleMode === "daily_scheduled" || scheduleMode === "immediate") {
        setPublishMode(scheduleMode as "immediate" | "scheduled" | "daily_scheduled");
      }
      setScheduledTime(String(upload?.scheduled_time || "22:00"));
      setConfigLoaded(true);
    } catch {
      // 首次进入后端未就绪时，短暂重试
      setTimeout(() => {
        loadQuickConfig().catch(() => undefined);
      }, 1200);
    } finally {
      setConfigLoading(false);
    }
  }, []);

  useEffect(() => {
    loadQuickConfig();
  }, [loadQuickConfig]);

  // 快速配置变更自动保存（防抖）
  useEffect(() => {
    if (!configLoaded) return;

    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current);
    }

    saveTimerRef.current = window.setTimeout(async () => {
      try {
        const root = configApi.getConfigRootSync() || {};
        const sections = await configApi.getSections(["upload", "image_norm", "payment"]);

        const next = {
          ...root,
          upload: {
            ...(sections.upload || {}),
            max_products_per_run: Number(maxProducts ?? 0),
            upload_interval_seconds: Number(uploadDelay || 15),
            schedule_mode: publishMode,
            scheduled_time: scheduledTime,
          },
          image_norm: {
            ...(sections.image_norm || {}),
            enable_showcase: !!enableShowcase,
          },
          payment: {
            ...(sections.payment || {}),
            enable_p4p: !!enableP4P,
          },
        };

        await configApi.update(next);
      } catch {
        // 自动保存失败不弹窗，避免打扰
      }
    }, 500);

    return () => {
      if (saveTimerRef.current) {
        window.clearTimeout(saveTimerRef.current);
      }
    };
  }, [configLoaded, maxProducts, uploadDelay, enableShowcase, enableP4P, publishMode, scheduledTime]);

  const handleStart = useCallback(async () => {
    try {
      const mode = publishMode === "scheduled" ? "scheduled" : publishMode === "daily_scheduled" ? "daily_scheduled" : "batch";
      await uploadApi.start({ mode, max_products: maxProducts, scheduled_time: publishMode !== "immediate" ? scheduledTime : undefined });
      setIsRunning(true);
      setIsPaused(false);
      if (publishMode === "scheduled" || publishMode === "daily_scheduled") {
        toast.warning("定时发品中，请勿退出软件");
      } else {
        toast.success("自动发品流程已启动");
      }
    } catch (e: any) {
      toast.error(e.message || "启动失败");
    }
  }, [maxProducts, publishMode, scheduledTime]);

  const handleStop = useCallback(async () => {
    try {
      await uploadApi.stop();
      setIsRunning(false);
      setIsPaused(false);
      toast.info("流程已停止");
    } catch (e: any) {
      toast.error(e.message || "停止失败");
    }
  }, []);

  const handlePause = useCallback(async () => {
    try {
      if (isPaused) {
        await uploadApi.resume();
        setIsPaused(false);
        toast.info("流程已恢复");
      } else {
        await uploadApi.pause();
        setIsPaused(true);
        toast.info("流程已暂停");
      }
    } catch (e: any) {
      toast.error(e.message || "操作失败");
    }
  }, [isPaused]);


  const calcPublishDays = (dateRaw: any): number | null => {
    const raw = String(dateRaw ?? "").trim();
    if (!raw) return null;

    let parsed: Date | null = null;
    const direct = new Date(raw.replace(/\./g, "-").replace("T", " "));
    if (!Number.isNaN(direct.getTime())) {
      parsed = direct;
    } else {
      const digits = raw.replace(/\D/g, "");
      if (digits.length >= 8) {
        const y = Number(digits.slice(0, 4));
        const m = Number(digits.slice(4, 6));
        const d = Number(digits.slice(6, 8));
        const dt = new Date(y, m - 1, d);
        if (!Number.isNaN(dt.getTime())) parsed = dt;
      } else if (digits.length === 6) {
        const y = 2000 + Number(digits.slice(0, 2));
        const m = Number(digits.slice(2, 4));
        const d = Number(digits.slice(4, 6));
        const dt = new Date(y, m - 1, d);
        if (!Number.isNaN(dt.getTime())) parsed = dt;
      }
    }

    if (!parsed) return null;
    const t = new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate()).getTime();
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    return Math.floor((today - t) / (24 * 60 * 60 * 1000));
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

  const loadNewProductsModule = useCallback(async () => {
    try {
      const da = (await configApi.getSection("data_analysis")) || {};
      const newLinksFilePath = da.new_links_file_path;

      const res: any = await analysisApi.getNewLinksMonitor(newLinksFilePath, undefined);
      const payload = res?.data || res;
      const data = payload?.data || payload || {};
      const cols: string[] = Array.isArray(data?.columns) ? data.columns.map((c: any) => String(c ?? "")) : [];
      const rows: any[] = Array.isArray(data?.rows) ? data.rows : [];

      const idCol = cols.find((c) => c.includes("新发链接")) || cols[1] || cols[0] || "";
      const dateCol = cols.find((c) => c.includes("发品") && (c.includes("日期") || c.includes("时间"))) || cols[0] || "";
      const typeCol = cols.find((c) => c.includes("类型")) || cols[2] || "";

      const mapped: NewProductRow[] = rows
        .map((r) => {
          const pid = normalizePid(r?.[idCol]);
          const publishDateRaw = r?.[dateCol] ?? "";
          const publishDays = calcPublishDays(publishDateRaw);
          const typeText = String(r?.[typeCol] ?? "").trim();
          return {
            product_id: pid,
            publish_date: String(publishDateRaw ?? "").trim(),
            type: typeText || "-",
            publish_days: publishDays,
          };
        })
        .filter((x) => !!x.product_id);

      const onlyNew = mapped.filter((x) => x.publish_days !== null && x.publish_days <= 30);
      onlyNew.sort((a, b) => {
        const da = String(a.publish_date || "").replace(/\D/g, "");
        const db = String(b.publish_date || "").replace(/\D/g, "");
        return db.localeCompare(da); // 日期越新越靠前
      });

      setNewProducts(onlyNew);
    } catch {
      setNewProducts([]);
    }
  }, []);

  useEffect(() => {
    loadNewProductsModule();
    const t = setInterval(() => {
      loadNewProductsModule();
    }, 4000);
    return () => clearInterval(t);
  }, [loadNewProductsModule]);

  return (
    <div className="p-8">
      {/* Page Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>产品上传</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">自动发品</span>
        </div>
        <h1 className="text-2xl font-bold text-foreground">自动发品管理</h1>
        <p className="text-sm text-muted-foreground mt-1">
          基于属性融合的阿里巴巴国际站自动产品发布系统
        </p>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Left: Process Steps */}
        <div className="col-span-2 space-y-6">
          {/* Control Bar */}
          <Card>
            <CardContent className="py-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {!isRunning ? (
                    <Button onClick={handleStart} className="gap-2">
                      <Play className="w-4 h-4" />
                      开始发品
                    </Button>
                  ) : (
                    <>
                      <Button
                        onClick={handlePause}
                        variant="outline"
                        className="gap-2"
                      >
                        {isPaused ? <Play className="w-4 h-4" /> : <Pause className="w-4 h-4" />}
                        {isPaused ? "恢复" : "暂停"}
                      </Button>
                      <Button
                        onClick={handleStop}
                        variant="destructive"
                        className="gap-2"
                      >
                        <Square className="w-4 h-4" />
                        停止
                      </Button>
                    </>
                  )}
                  <Button
                    variant="outline"
                    onClick={() => {
                      clearLogs();
                      streamLogCountRef.current = 0;
                      lastStatusLogRef.current = "";
                      setRuntimeLogs(["[系统] 日志已清空"]);
                    }}
                    className="gap-2"
                  >
                    <RotateCcw className="w-4 h-4" />
                    清空日志
                  </Button>
                </div>
                <div className="flex items-center gap-4">
                  <Badge variant={isRunning ? (isPaused ? "secondary" : "default") : "secondary"} className="gap-1.5">
                    {isRunning ? (
                      isPaused ? (
                        <span className="w-1.5 h-1.5 rounded-full bg-yellow-400" />
                      ) : (
                        <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
                      )
                    ) : (
                      <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
                    )}
                    {isRunning ? (isPaused ? "已暂停" : "运行中") : "待启动"}
                  </Badge>
                  {taskStatus && (
                    <span className="text-sm text-muted-foreground">
                      {taskStatus.progress ?? 0}/{taskStatus.total ?? 0} 个产品
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

          {/* 新发品模块 */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">新发品模块</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="rounded-lg border border-border/50 overflow-auto h-[360px]">
                <table className="min-w-full text-sm">
                  <thead className="bg-muted/60 sticky top-0 z-10">
                    <tr className="border-b">
                      <th className="text-left py-2 px-3 text-xs font-medium text-muted-foreground">产品ID（新发链接）</th>
                      <th className="text-left py-2 px-3 text-xs font-medium text-muted-foreground">发品日期</th>
                      <th className="text-left py-2 px-3 text-xs font-medium text-muted-foreground">类型</th>
                    </tr>
                  </thead>
                  <tbody>
                    {newProducts.map((row, idx) => (
                      <tr key={`${row.product_id}-${idx}`} className="border-b last:border-0 align-top">
                        <td className="py-2 px-3 text-xs font-mono whitespace-nowrap">{row.product_id}</td>
                        <td className="py-2 px-3 text-xs whitespace-nowrap">{row.publish_date || "-"}</td>
                        <td className="py-2 px-3 text-xs whitespace-nowrap">{row.type || "-"}</td>
                      </tr>
                    ))}
                    {!newProducts.length && (
                      <tr>
                        <td className="py-6 px-3 text-center text-xs text-muted-foreground" colSpan={3}>暂无新发品数据</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          {/* Logs */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <FileText className="w-4 h-4" />
                运行日志
                <Badge variant="secondary" className="ml-2 text-[10px]">{runtimeLogs.length} 条</Badge>
              </CardTitle>
            </CardHeader>
            <CardContent>
              <ScrollArea className="h-48 rounded-lg bg-gray-950 p-4">
                <div className="space-y-1 font-mono text-xs">
                  {runtimeLogs.length === 0 ? (
                    <div className="text-gray-500">[系统] 等待启动...</div>
                  ) : (
                    runtimeLogs.map((log, i) => (
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

        {/* Right: Config Panel */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <Settings className="w-4 h-4" />
                快速配置{configLoading ? "（加载中）" : ""}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">发品模式</Label>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    className="w-full sm:w-auto"
                    variant={publishMode === "immediate" ? "default" : "outline"}
                    onClick={() => setPublishMode("immediate")}
                    disabled={isRunning}
                  >
                    立刻发品
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    className="w-full sm:w-auto"
                    variant={publishMode === "scheduled" ? "default" : "outline"}
                    onClick={() => setPublishMode("scheduled")}
                    disabled={isRunning}
                  >
                    定时发品（单次）
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    className="w-full sm:w-auto"
                    variant={publishMode === "daily_scheduled" ? "default" : "outline"}
                    onClick={() => setPublishMode("daily_scheduled")}
                    disabled={isRunning}
                  >
                    每日定时循环
                  </Button>
                </div>
              </div>

              {(publishMode === "scheduled" || publishMode === "daily_scheduled") && (
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground">定时发品时间（HH:MM）</Label>
                  <Input
                    type="time"
                    value={scheduledTime}
                    onChange={(e) => setScheduledTime(e.target.value || "22:00")}
                    className="text-sm"
                    disabled={isRunning}
                  />
                  <div className="text-[11px] text-amber-600 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                    定时发品中，请勿退出软件
                  </div>
                </div>
              )}

              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">最大发品数量</Label>
                <Input
                  type="text"
                  inputMode="numeric"
                  value={maxProductsInput}
                  onChange={(e) => {
                    const next = e.target.value.replace(/[^\d]/g, "");
                    setMaxProductsInput(next);
                  }}
                  placeholder="留空表示不限制"
                  className="text-sm"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">发品间隔(秒)</Label>
                <Input
                  type="number"
                  value={uploadDelay}
                  onChange={(e) => setUploadDelay(parseInt(e.target.value) || 15)}
                  className="text-sm"
                />
              </div>
              <Separator />

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label className="text-sm">启用橱窗</Label>
                  <Switch
                    checked={enableShowcase}
                    onCheckedChange={setEnableShowcase}
                  />
                </div>
                <div className="flex items-center justify-between">
                  <Label className="text-sm">启用P4P推广</Label>
                  <Switch
                    checked={enableP4P}
                    onCheckedChange={setEnableP4P}
                  />
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Attribute Fusion Info */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <Layers className="w-4 h-4" />
                属性融合说明
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3 text-xs text-muted-foreground">
                <div className="flex items-start gap-2">
                  <AlertCircle className="w-3.5 h-3.5 mt-0.5 text-amber-500 shrink-0" />
                  <span>系统会自动读取Excel中的属性列，与阿里巴巴平台属性进行智能匹配</span>
                </div>
                <div className="flex items-start gap-2">
                  <AlertCircle className="w-3.5 h-3.5 mt-0.5 text-amber-500 shrink-0" />
                  <span>属性填写满足40%差异规则，避免重复产品被平台降权</span>
                </div>
                <div className="flex items-start gap-2">
                  <AlertCircle className="w-3.5 h-3.5 mt-0.5 text-amber-500 shrink-0" />
                  <span>阶梯价格根据出厂价自动计算，支持随机浮动</span>
                </div>
                <div className="flex items-start gap-2">
                  <AlertCircle className="w-3.5 h-3.5 mt-0.5 text-amber-500 shrink-0" />
                  <span>详情图按文件夹名称自动匹配产品</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
