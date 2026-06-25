/**
 * AI 生图 — 批量电商图生成（Gemini 出图 + 豆包策划）
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { imageApi, createLogSocket, membershipApi, configApi, hasApiCredentials, getMembershipToken, isDesktopClient, ensureRuntimeSecretsForAiTask } from "@/lib/api";
import { useAdminRuntimeConfigSync, isMaskedSecret } from "@/hooks/useAdminRuntimeConfigSync";
import {
  ChevronRight,
  Play,
  Pause,
  RefreshCw,
  Sparkles,
  FolderOpen,
  ImageIcon,
  Wand2,
  Settings2,
  Loader2,
} from "lucide-react";

const ASPECT_RATIO_OPTIONS = ["16:9", "4:3", "1:1", "3:4", "9:16"] as const;
const IMAGE_SIZE_OPTIONS = ["1K", "2K", "4K"] as const;

const DEFAULT_AI_IMAGE_POINTS_COST: Record<string, number> = {
  "1K": 0.6,
  "2K": 0.7,
  "4K": 0.85,
};

/** 受控 number 输入：清空时不写入 0（Number("") === 0 会导致无法删光） */
function numericInputDisplay(value: unknown): string | number {
  if (value === "" || value === null || value === undefined) return "";
  return typeof value === "number" && Number.isFinite(value) ? value : "";
}

function parseNumericInput(raw: string): number | "" {
  if (raw === "") return "";
  const n = parseInt(raw, 10);
  return Number.isNaN(n) ? "" : n;
}

function resolveNumericConfig(value: unknown, fallback: number, min: number, max: number): number {
  const n = typeof value === "number" ? value : parseInt(String(value), 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

type InputItem = {
  folder: string;
  folder_rel: string;
  image: string;
  image_path: string;
  has_txt: boolean;
  has_prompt_cache: boolean;
  prompt_cache_path?: string;
};

type OutputItem = {
  product: string;
  filename: string;
  path: string;
  size: number;
};

export default function AiImageGen() {
  const [running, setRunning] = useState(false);
  const [starting, setStarting] = useState(false);
  const [logs, setLogs] = useState<string[]>(["[就绪] AI 生图工作台已加载"]);
  const [taskProgress, setTaskProgress] = useState<{ progress: number; total: number } | null>(null);
  const [config, setConfig] = useState<Record<string, any>>({});
  const [inputs, setInputs] = useState<InputItem[]>([]);
  const [outputs, setOutputs] = useState<OutputItem[]>([]);
  const [gallerySource, setGallerySource] = useState<string>("");
  const [selectedProduct, setSelectedProduct] = useState<string>("");
  const [previewMap, setPreviewMap] = useState<Record<string, string>>({});
  const [showSettings, setShowSettings] = useState(false);
  const [promptPreview, setPromptPreview] = useState<{ title: string; text: string } | null>(null);
  const [pointsBalance, setPointsBalance] = useState<number | null>(null);
  const [pointsEstimate, setPointsEstimate] = useState<Record<string, any> | null>(null);
  const [pointsCostBySize, setPointsCostBySize] = useState<Record<string, number>>(DEFAULT_AI_IMAGE_POINTS_COST);
  const wsConnectedRef = useRef(false);
  const logEndRef = useRef<HTMLDivElement>(null);
  const lastStatusKeyRef = useRef("");
  const lastPolledLogCountRef = useRef(0);
  const wasBusyRef = useRef(false);

  const isBusy = starting || running;

  const appendLog = useCallback((line: string) => {
    const text = String(line || "").trim();
    if (!text) return;
    setLogs((prev) => {
      if (prev[prev.length - 1] === text) return prev;
      const recent = prev.slice(-30);
      if (recent.includes(text)) return prev;
      return [...prev, text].slice(-500);
    });
  }, []);

  const formatTime = () => new Date().toLocaleTimeString();

  const isAdminSession = useMemo(() => {
    try {
      return (localStorage.getItem("admin_console_logged_in") || "") === "1";
    } catch {
      return false;
    }
  }, []);

  const BASIC_CONFIG_KEYS = [
    "input_root_dir",
    "generations_per_image",
    "aspect_ratio",
    "image_size",
    "user_requirement",
    "sku_generations_count",
    "sku_names",
  ] as const;

  const products = useMemo(() => {
    const set = new Set<string>();
    inputs.forEach((x) => set.add(x.image.replace(/\\.[^.]+$/, "")));
    outputs.forEach((x) => set.add(x.product));
    return Array.from(set).sort();
  }, [inputs, outputs]);

  const filteredOutputs = useMemo(() => {
    if (!selectedProduct) return outputs;
    return outputs.filter((x) => x.product === selectedProduct);
  }, [outputs, selectedProduct]);

  const currentImageSize = String(config.image_size || "1K").toUpperCase();
  const perImageCost = pointsCostBySize[currentImageSize] ?? pointsCostBySize["1K"] ?? 0.6;

  const refreshPointsPricing = useCallback(async () => {
    try {
      const res: any = await imageApi.getAiGenPointsPricing();
      const payload = res?.data ?? res;
      const data = payload?.data ?? payload ?? {};
      const costs = data?.cost_per_size;
      if (costs && typeof costs === "object") {
        const next: Record<string, number> = { ...DEFAULT_AI_IMAGE_POINTS_COST };
        for (const k of ["1K", "2K", "4K"]) {
          const v = Number((costs as Record<string, number>)[k]);
          if (Number.isFinite(v) && v >= 0) next[k] = v;
        }
        setPointsCostBySize(next);
      }
    } catch {
      // keep default
    }
  }, []);

  const refreshPointsEstimate = useCallback(async () => {
    if (isAdminSession) {
      setPointsEstimate({ skip_points: true });
      return;
    }
    try {
      const res: any = await imageApi.getAiGenPointsEstimate();
      const payload = res?.data ?? res;
      const estimate = payload?.data ?? payload ?? null;
      setPointsEstimate(estimate);
      if (estimate && typeof estimate.balance === "number") {
        setPointsBalance(estimate.balance);
      }
    } catch {
      setPointsEstimate(null);
    }
  }, [isAdminSession]);

  const loadPointsBalance = useCallback(async () => {
    if (isAdminSession) {
      setPointsBalance(null);
      return;
    }
    try {
      const res: any = await membershipApi.me();
      const body = res?.data ?? res;
      const me = body?.data ?? body;
      if (me?.points_unavailable) {
        setPointsBalance(null);
      } else {
        setPointsBalance(Number(me?.points_balance ?? 0));
      }
    } catch {
      setPointsBalance(null);
    }
  }, [isAdminSession]);

  const loadConfig = async () => {
    try {
      const res: any = await imageApi.getAiGenConfig();
      const payload = res?.data ?? res;
      setConfig(payload?.data ?? payload ?? {});
    } catch (e: any) {
      toast.error(e.message || "加载配置失败");
    }
  };

  useAdminRuntimeConfigSync({
    enabled: isDesktopClient() && !!getMembershipToken(),
    onAiImageGenChange: (patch) => {
      if (!patch || typeof patch !== "object") return;
      setConfig((prev) => {
        const next = { ...prev };
        for (const [k, v] of Object.entries(patch)) {
          if (v === undefined) continue;
          if ((k === "gemini_api_key" || k === "doubao_api_key") && String(v) === "***") continue;
          next[k] = v;
        }
        return next;
      });
    },
  });

  const saveConfig = async (silent = false) => {
    try {
      let payload: Record<string, any> = { ...config };
      if (!isAdminSession) {
        payload = Object.fromEntries(
          BASIC_CONFIG_KEYS.filter((k) => k in config).map((k) => [k, config[k]])
        );
      }
      if (payload.gemini_api_key && isMaskedSecret(String(payload.gemini_api_key))) delete payload.gemini_api_key;
      if (payload.doubao_api_key && isMaskedSecret(String(payload.doubao_api_key))) delete payload.doubao_api_key;
      if (typeof payload.prompt_templates === "string") {
        payload.prompt_templates = (payload.prompt_templates as string)
          .split("\\n")
          .map((s) => s.trim())
          .filter(Boolean);
      }
      if (typeof payload.prompt_source_priority === "string") {
        payload.prompt_source_priority = (payload.prompt_source_priority as string)
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
      }
      if ("generations_per_image" in payload) {
        payload.generations_per_image = resolveNumericConfig(
          payload.generations_per_image,
          6,
          1,
          20
        );
      }
      if ("sku_generations_count" in payload) {
        const raw = payload.sku_generations_count;
        if (raw === "" || raw == null) {
          payload.sku_generations_count = 0;
        } else {
          payload.sku_generations_count = resolveNumericConfig(raw, 0, 0, 20);
        }
      }
      if (typeof payload.sku_names === "string") {
        payload.sku_names = (payload.sku_names as string)
          .split(/[\n,，、]/)
          .map((s) => s.trim())
          .filter(Boolean);
      }
      const res: any = await imageApi.updateAiGenConfig(payload);
      const body = res?.data ?? res;
      setConfig(body?.data ?? body ?? config);
      configApi.invalidateCache();
      if (!silent) toast.success("配置已保存");
    } catch (e: any) {
      toast.error(e.message || "保存失败");
      throw e;
    }
  };

  const refreshInputs = async () => {
    try {
      const res: any = await imageApi.getAiGenInputs();
      const payload = res?.data ?? res;
      setInputs(Array.isArray(payload?.data) ? payload.data : Array.isArray(payload) ? payload : []);
    } catch {
      setInputs([]);
    }
  };

  const refreshOutputs = async () => {
    try {
      const res: any = await imageApi.getAiGenOutputs(selectedProduct || undefined);
      const payload = res?.data ?? res;
      setOutputs(Array.isArray(payload?.data) ? payload.data : Array.isArray(payload) ? payload : []);
      setGallerySource(String(payload?.gallery_source || "").trim());
    } catch {
      setOutputs([]);
      setGallerySource("");
    }
  };

  const refreshStatus = async () => {
    try {
      const res: any = await imageApi.getAiGenStatus();
      const payload = res?.data ?? res;
      const status = payload?.data ?? payload;
      const isRunning = status?.status === "running" || status?.status === "stopping";
      const wasBusy = wasBusyRef.current;
      wasBusyRef.current = isRunning || starting;
      setRunning(isRunning);

      if (typeof status?.progress === "number" && typeof status?.total === "number") {
        setTaskProgress({ progress: status.progress, total: status.total });
      }

      const statusKey = `${status?.status || ""}|${status?.progress || 0}|${status?.current_step || ""}|${status?.error || ""}`;
      if (statusKey !== lastStatusKeyRef.current) {
        lastStatusKeyRef.current = statusKey;
        if (status?.current_step) {
          const progressText =
            typeof status?.progress === "number" && typeof status?.total === "number" && status.total > 0
              ? ` (${status.progress}/${status.total})`
              : "";
          appendLog(`[状态${progressText}] ${status.current_step}`);
        }
        if (status?.error) {
          appendLog(`[错误] ${status.error}`);
        }
      }

      if (wasBusy && !isRunning) {
        if (status?.status === "completed") {
          appendLog(`[完成] ${status?.current_step || "AI 生图任务已完成"}`);
          toast.success("AI 生图任务已完成");
        } else if (status?.status === "failed") {
          appendLog(`[失败] ${status?.error || "任务执行失败"}`);
          toast.error(status?.error || "AI 生图任务失败");
        }
        setTaskProgress(null);
        refreshInputs();
        refreshOutputs();
        loadPointsBalance();
        refreshPointsEstimate();
      }

      return status;
    } catch {
      return null;
    }
  };

  const refreshRecentLogs = async () => {
    if (wsConnectedRef.current) return;
    try {
      const res: any = await imageApi.getAiGenRecentLogs(200);
      const payload = res?.data ?? res;
      const data = payload?.data ?? payload;
      const items = Array.isArray(data?.items) ? data.items : [];
      if (items.length <= lastPolledLogCountRef.current) return;
      const slice = items.slice(lastPolledLogCountRef.current);
      lastPolledLogCountRef.current = items.length;
      slice.forEach((entry: any) => {
        const msg = entry?.message || entry?.msg || entry?.text;
        if (msg) appendLog(String(msg));
      });
    } catch {
      // ignore
    }
  };

  const handleStart = async () => {
    if (isBusy) return;
    try {
      setStarting(true);
      wasBusyRef.current = true;
      lastPolledLogCountRef.current = 0;
      appendLog(`[${formatTime()}] 正在保存配置...`);

      await saveConfig(true);
      appendLog(`[${formatTime()}] 配置已保存，正在同步总部 API 配置...`);
      await ensureRuntimeSecretsForAiTask();
      appendLog(`[${formatTime()}] API 配置已就绪，校验积分并启动任务...`);

      if (!isAdminSession) {
        let estimate: Record<string, any> | null = null;
        try {
          const res: any = await imageApi.getAiGenPointsEstimate();
          const payload = res?.data ?? res;
          estimate = payload?.data ?? payload ?? null;
          setPointsEstimate(estimate);
        } catch {
          estimate = null;
        }
        if (estimate && estimate.skip_points !== true && estimate.sufficient === false) {
          toast.error(
            `积分不足：余额 ${estimate.balance ?? 0}，预计至少需 ${estimate.estimated_total_cost ?? estimate.whole_points_required ?? 0} 积分`
          );
          appendLog(`[${formatTime()}] 启动中止：积分不足`);
          wasBusyRef.current = false;
          return;
        }
      }

      await imageApi.startAiGen();
      setRunning(true);
      appendLog(`[${formatTime()}] 任务已提交，正在执行批量生图...`);
      toast.success("AI 生图任务已启动");
      loadPointsBalance();
      refreshStatus();
      refreshRecentLogs();
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e.message || "启动失败";
      appendLog(`[${formatTime()}] 启动失败：${msg}`);
      toast.error(msg);
      setRunning(false);
      wasBusyRef.current = false;
    } finally {
      setStarting(false);
    }
  };

  const handleStop = async () => {
    try {
      appendLog(`[${formatTime()}] 正在发送停止指令...`);
      await imageApi.stopAiGen();
      toast.info("已发送停止指令");
      refreshStatus();
    } catch (e: any) {
      toast.error(e.message || "停止失败");
    }
  };

  const loadPreview = useCallback(async (path: string) => {
    if (!path || previewMap[path]) return;
    try {
      const res: any = await imageApi.getImageFileBlob(path);
      const blob = res?.data instanceof Blob ? res.data : res;
      if (blob instanceof Blob) {
        const url = URL.createObjectURL(blob);
        setPreviewMap((prev) => ({ ...prev, [path]: url }));
      }
    } catch {
      // ignore
    }
  }, [previewMap]);

  useEffect(() => {
    loadConfig();
    refreshInputs();
    refreshOutputs();
    refreshStatus();
    refreshPointsPricing();
    loadPointsBalance();
    refreshPointsEstimate();
  }, []);

  useEffect(() => {
    refreshPointsEstimate();
  }, [config.image_size, config.generations_per_image, config.sku_generations_count, inputs.length, refreshPointsEstimate]);

  useEffect(() => {
    refreshOutputs();
  }, [selectedProduct]);

  useEffect(() => {
    inputs.slice(0, 24).forEach((item) => loadPreview(item.image_path));
    filteredOutputs.slice(0, 36).forEach((item) => loadPreview(item.path));
  }, [inputs, filteredOutputs, loadPreview]);

  useEffect(() => {
    if (!isBusy) return;
    const timer = setInterval(() => {
      refreshStatus();
      if (!wsConnectedRef.current) {
        refreshRecentLogs();
      }
    }, 1500);
    return () => clearInterval(timer);
  }, [isBusy, selectedProduct]);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [logs]);

  useEffect(() => {
    const ws = createLogSocket((data) => {
      wsConnectedRef.current = true;
      const payload = data?.data || data;
      const moduleName = String(payload?.module || "");
      const msg = payload?.message || payload?.msg || payload?.text;
      if (!msg) return;
      if (moduleName && moduleName !== "ai_image_gen") return;
      appendLog(String(msg));
    });
    return () => {
      try {
        ws?.close();
      } catch {
        // ignore
      }
    };
  }, [appendLog]);

  const loadPromptCache = async (item: InputItem, e?: React.MouseEvent) => {
    e?.stopPropagation();
    try {
      const res: any = await imageApi.getAiGenPrompts(item.image_path);
      const body = res?.data ?? res;
      const data = body?.data ?? body;
      const text = data?.exists
        ? JSON.stringify(data.data, null, 2)
        : "暂无提示词缓存，运行后会生成 图名_prompts.json";
      setPromptPreview({ title: `${item.image} 提示词`, text });
    } catch (err: any) {
      toast.error(err.message || "读取提示词失败");
    }
  };

  const setField = (key: string, value: any) => {
    setConfig((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <div className="min-h-full p-8">
      <div className="relative overflow-hidden rounded-2xl border border-slate-800/60 bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 p-8 mb-6">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(99,102,241,0.18),transparent_40%),radial-gradient(circle_at_80%_0%,rgba(14,165,233,0.12),transparent_35%)]" />
        <div className="relative z-10 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm text-slate-400 mb-2">
              <span>图片管理</span>
              <ChevronRight className="w-3.5 h-3.5" />
              <span className="text-slate-200">AI 生图</span>
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-white flex items-center gap-3">
              <Sparkles className="w-8 h-8 text-indigo-300" />
              批量生图主图
            </h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-300/90">
              批量读取原图目录，自动策划提示词 + 自动生成电商风格图。
              {!isAdminSession && (
                <span className="block mt-1 text-slate-400">
                  当前画质 {currentImageSize}：每张成功出图扣 {perImageCost} 积分
                  {pointsBalance !== null ? ` · 余额 ${pointsBalance}` : ""}
                  {pointsEstimate && !pointsEstimate.skip_points && pointsEstimate.planned_images > 0
                    ? ` · 预计约 ${pointsEstimate.estimated_total_cost ?? (pointsEstimate.planned_images * perImageCost).toFixed(2)} 积分（${pointsEstimate.planned_images} 张）`
                    : ""}
                </span>
              )}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="border-indigo-400/40 text-indigo-200 bg-indigo-500/10">
              {starting ? "启动中" : running ? "生成中" : "空闲"}
            </Badge>
            {taskProgress && isBusy && (
              <Badge variant="outline" className="border-slate-500/40 text-slate-200 bg-slate-500/10">
                {taskProgress.progress}/{taskProgress.total}
              </Badge>
            )}
            <Button size="sm" variant="outline" className="border-slate-600 text-slate-200 hover:bg-slate-800" onClick={() => setShowSettings((v) => !v)}>
              <Settings2 className="w-4 h-4 mr-1" />
              设置
            </Button>
            {running && (
              <Button size="sm" variant="destructive" onClick={handleStop} className="gap-1.5">
                <Pause className="w-4 h-4" />
                停止
              </Button>
            )}
            <Button
              size="sm"
              className="bg-indigo-500 hover:bg-indigo-400 text-white min-w-[112px]"
              onClick={handleStart}
              disabled={isBusy}
            >
              {starting ? (
                <>
                  <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                  启动中...
                </>
              ) : running ? (
                <>
                  <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                  生成中...
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 mr-1" />
                  开始生成
                </>
              )}
            </Button>
          </div>
        </div>
      </div>

      {showSettings && (
        <Card className="mb-6 border-slate-200/80 shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Wand2 className="w-4 h-4" />
              {isAdminSession ? "生成配置（完整原脚本参数）" : "生成配置"}
            </CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 max-h-[70vh] overflow-y-auto pr-2">
            <div className="space-y-1.5">
              <Label className="text-xs">原图目录</Label>
              <Input value={config.input_root_dir || ""} onChange={(e) => setField("input_root_dir", e.target.value)} className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5 md:col-span-2">
              <Label className="text-xs">成图保存位置</Label>
              <p className="text-[11px] text-muted-foreground leading-relaxed rounded-md border bg-muted/30 px-2 py-1.5">
                生成图直接写入「配置管理 → 路径配置」中的<strong>首图文件夹</strong>与<strong>主图文件夹</strong>，无需单独设置输出目录。
              </p>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">每张原图生成数</Label>
              <Input
                type="number"
                min={1}
                max={20}
                value={numericInputDisplay(config.generations_per_image)}
                placeholder="6"
                onChange={(e) => setField("generations_per_image", parseNumericInput(e.target.value))}
                onBlur={() => {
                  const v = config.generations_per_image;
                  if (v === "" || v == null || !Number.isFinite(Number(v)) || Number(v) < 1) {
                    setField("generations_per_image", 6);
                  }
                }}
              />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">生成 SKU 图数量</Label>
              <Input
                type="number"
                min={0}
                max={20}
                value={
                  config.sku_generations_count === "" ||
                  config.sku_generations_count == null ||
                  Number(config.sku_generations_count) === 0
                    ? ""
                    : numericInputDisplay(config.sku_generations_count)
                }
                placeholder="留空不生成"
                onChange={(e) => setField("sku_generations_count", parseNumericInput(e.target.value))}
                onBlur={() => {
                  const v = config.sku_generations_count;
                  if (v === "" || v == null || !Number.isFinite(Number(v)) || Number(v) < 0) {
                    setField("sku_generations_count", 0);
                  }
                }}
              />
              <p className="text-[11px] text-muted-foreground">留空或 0 表示不生成 SKU 图；填写数量后豆包会额外策划 SKU 提示词（1:1 比例）。原图目录 txt 中若含「SKU：红色，白色」等行，以 txt 为准并覆盖此处设置</p>
            </div>
            <div className="space-y-1.5 md:col-span-2">
              <Label className="text-xs">SKU 名称（可选）</Label>
              <Textarea
                rows={2}
                value={
                  Array.isArray(config.sku_names)
                    ? config.sku_names.join("\n")
                    : typeof config.sku_names === "string"
                      ? config.sku_names
                      : ""
                }
                onChange={(e) => setField("sku_names", e.target.value)}
                placeholder={"每行一个，例如：\n红色\n蓝色\n绿色\n留空则由豆包自主策划变体名称"}
                className="text-xs font-mono"
                disabled={!config.sku_generations_count}
              />
              <p className="text-[11px] text-muted-foreground">
                指定需要生成的 SKU 规格（如颜色）；数量可与上方 SKU 图数量一致，留空则无名称约束。保存文件名会自动转为英文（如 红色 → Red.jpg）
              </p>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">SKU图片比例</Label>
              <select
                className="flex h-9 w-full rounded-md border border-input bg-background px-2 text-xs"
                value={ASPECT_RATIO_OPTIONS.includes(config.aspect_ratio) ? config.aspect_ratio : "1:1"}
                onChange={(e) => setField("aspect_ratio", e.target.value)}
              >
                {ASPECT_RATIO_OPTIONS.map((v) => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">图片质量</Label>
              <select
                className="flex h-9 w-full rounded-md border border-input bg-background px-2 text-xs"
                value={IMAGE_SIZE_OPTIONS.includes(config.image_size) ? config.image_size : "1K"}
                onChange={(e) => setField("image_size", e.target.value)}
              >
                {IMAGE_SIZE_OPTIONS.map((v) => (
                  <option key={v} value={v}>
                    {v}（{pointsCostBySize[v] ?? DEFAULT_AI_IMAGE_POINTS_COST[v]} 积分/张）
                  </option>
                ))}
              </select>
              {!isAdminSession && (
                <p className="text-[11px] text-muted-foreground">
                  1K={pointsCostBySize["1K"]} · 2K={pointsCostBySize["2K"]} · 4K={pointsCostBySize["4K"]} 积分/张（仅成功生成扣费，跳过已存在文件不扣）
                </p>
              )}
            </div>
            <div className="space-y-1.5 md:col-span-2 xl:col-span-3">
              <Label className="text-xs">用户需求描述</Label>
              <Textarea rows={3} value={config.user_requirement || ""} onChange={(e) => setField("user_requirement", e.target.value)} placeholder="也可在原图目录放 需求.txt" className="text-xs" />
            </div>

            {isAdminSession && (
              <>
            <div className="space-y-1.5">
              <Label className="text-xs">Gemini API Key</Label>
              <Input type="password" value={config.gemini_api_key || ""} onChange={(e) => setField("gemini_api_key", e.target.value)} placeholder="或环境变量 GEMINI_API_KEY" className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Gemini 模型</Label>
              <Input value={config.gemini_model || ""} onChange={(e) => setField("gemini_model", e.target.value)} className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Gemini Base URL</Label>
              <Input value={config.gemini_base_url || ""} onChange={(e) => setField("gemini_base_url", e.target.value)} className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">并发 / 提示词线程</Label>
              <div className="flex gap-2">
                <Input type="number" min={1} value={config.concurrent_workers ?? 5} onChange={(e) => setField("concurrent_workers", Number(e.target.value))} className="text-xs" />
                <Input type="number" min={1} value={config.prompt_workers ?? 2} onChange={(e) => setField("prompt_workers", Number(e.target.value))} className="text-xs" />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">缩图边长 / JPEG 质量</Label>
              <div className="flex gap-2">
                <Input type="number" value={config.resize_max_edge ?? 1280} onChange={(e) => setField("resize_max_edge", Number(e.target.value))} className="text-xs" />
                <Input type="number" value={config.jpeg_quality ?? 82} onChange={(e) => setField("jpeg_quality", Number(e.target.value))} className="text-xs" />
              </div>
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">全局 Gemini 线程池</Label>
              <Switch checked={config.global_gemini_pool !== false} onCheckedChange={(v) => setField("global_gemini_pool", v)} />
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">Gemini 流式接口</Label>
              <Switch checked={!!config.use_stream} onCheckedChange={(v) => setField("use_stream", v)} />
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">跳过已生成</Label>
              <Switch checked={config.skip_existing !== false} onCheckedChange={(v) => setField("skip_existing", v)} />
            </div>
            <div className="space-y-1.5 md:col-span-2">
              <Label className="text-xs">Gemini 重试 / 间隔 / 请求间隔</Label>
              <div className="flex gap-2">
                <Input type="number" value={config.max_retries ?? 3} onChange={(e) => setField("max_retries", Number(e.target.value))} className="text-xs" />
                <Input type="number" value={config.retry_delay ?? 6} onChange={(e) => setField("retry_delay", Number(e.target.value))} className="text-xs" />
                <Input type="number" value={config.request_interval ?? 0} onChange={(e) => setField("request_interval", Number(e.target.value))} className="text-xs" />
              </div>
            </div>
            <div className="md:col-span-2 xl:col-span-3 text-xs font-semibold text-muted-foreground pt-2 border-t">策划</div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">启用策划</Label>
              <Switch checked={!!config.doubao_enabled} onCheckedChange={(v) => setField("doubao_enabled", v)} />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">豆包 API Key</Label>
              <Input type="password" value={config.doubao_api_key || ""} onChange={(e) => setField("doubao_api_key", e.target.value)} placeholder="或环境变量 ARK_API_KEY" className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5 md:col-span-2">
              <Label className="text-xs">豆包模型 / Base URL</Label>
              <div className="flex gap-2">
                <Input value={config.doubao_model || ""} onChange={(e) => setField("doubao_model", e.target.value)} className="text-xs font-mono" />
                <Input value={config.doubao_base_url || ""} onChange={(e) => setField("doubao_base_url", e.target.value)} className="text-xs font-mono" />
              </div>
            </div>
            <div className="space-y-1.5 md:col-span-2">
              <Label className="text-xs">doubao_ep.txt 路径（ep- 接入点）</Label>
              <Input value={config.doubao_ep_file || ""} onChange={(e) => setField("doubao_ep_file", e.target.value)} placeholder="留空则自动查找" className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">输出语言</Label>
              <Input value={config.doubao_output_language || "English"} onChange={(e) => setField("doubao_output_language", e.target.value)} className="text-xs" />
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">启动探测</Label>
              <Switch checked={config.doubao_probe_on_startup !== false} onCheckedChange={(v) => setField("doubao_probe_on_startup", v)} />
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">探测失败即中止</Label>
              <Switch checked={!!config.doubao_probe_strict} onCheckedChange={(v) => setField("doubao_probe_strict", v)} />
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">缓存提示词 JSON</Label>
              <Switch checked={config.cache_prompts !== false} onCheckedChange={(v) => setField("cache_prompts", v)} />
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">优先用缓存</Label>
              <Switch checked={config.use_cached_prompts !== false} onCheckedChange={(v) => setField("use_cached_prompts", v)} />
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">强制刷新豆包策划</Label>
              <Switch checked={!!config.force_refresh} onCheckedChange={(v) => setField("force_refresh", v)} />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">豆包重试 / 延迟</Label>
              <div className="flex gap-2">
                <Input type="number" value={config.doubao_max_retries ?? 3} onChange={(e) => setField("doubao_max_retries", Number(e.target.value))} className="text-xs" />
                <Input type="number" value={config.doubao_retry_delay ?? 5} onChange={(e) => setField("doubao_retry_delay", Number(e.target.value))} className="text-xs" />
              </div>
            </div>
            <div className="md:col-span-2 xl:col-span-3 text-xs font-semibold text-muted-foreground pt-2 border-t">提示词策略</div>
            <div className="space-y-1.5 md:col-span-2 xl:col-span-3">
              <Label className="text-xs">来源优先级（逗号分隔）</Label>
              <Input value={Array.isArray(config.prompt_source_priority) ? config.prompt_source_priority.join(", ") : "cache, doubao, txt"} onChange={(e) => setField("prompt_source_priority", e.target.value)} className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5 md:col-span-2 xl:col-span-3">
              <Label className="text-xs">兜底任务类型（每行一条）</Label>
              <Textarea rows={2} value={Array.isArray(config.prompt_templates) ? config.prompt_templates.join("\n") : ""} onChange={(e) => setField("prompt_templates", e.target.value)} className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5 md:col-span-2 xl:col-span-3">
              <Label className="text-xs">豆包策划系统指令（DOUBAO_PLANNER_PROMPT）</Label>
              <Textarea rows={10} value={config.doubao_planner_prompt || ""} onChange={(e) => setField("doubao_planner_prompt", e.target.value)} className="text-xs font-mono leading-relaxed" />
            </div>
              </>
            )}

            <div className="md:col-span-2 xl:col-span-3 flex gap-2 pb-2">
              <Button size="sm" onClick={() => saveConfig()}>保存配置</Button>
              <Button size="sm" variant="outline" onClick={loadConfig}>重新加载</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        <Card className="xl:col-span-4 border-slate-200/80">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <FolderOpen className="w-4 h-4" />
                原图素材
              </CardTitle>
              <Button size="sm" variant="ghost" className="h-8" onClick={refreshInputs}>
                <RefreshCw className="w-3.5 h-3.5" />
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">{config.input_root_dir || "未配置原图目录"}</p>
            <p className="text-xs text-muted-foreground">原图命名规范：自由名-场景-价格</p>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3 max-h-[520px] overflow-auto pr-1">
              {inputs.length === 0 ? (
                <div className="col-span-2 py-10 text-center text-xs text-muted-foreground">暂无原图，请检查原图目录配置</div>
              ) : (
                inputs.map((item) => (
                  <div key={item.image_path} className="rounded-xl border bg-muted/20 overflow-hidden hover:border-indigo-300 cursor-pointer" onClick={() => setSelectedProduct(item.image.replace(/\\.[^.]+$/, ""))}>
                    <div className="aspect-square bg-slate-100 flex items-center justify-center overflow-hidden">
                      {previewMap[item.image_path] ? (
                        <img src={previewMap[item.image_path]} alt={item.image} className="w-full h-full object-cover" />
                      ) : (
                        <ImageIcon className="w-8 h-8 text-slate-300" />
                      )}
                    </div>
                    <div className="p-2 space-y-1">
                      <div className="text-[11px] font-medium truncate" title={item.image}>{item.image}</div>
                      <div className="flex gap-1 flex-wrap">
                        {item.has_txt && <Badge variant="secondary" className="text-[10px] h-5">txt</Badge>}
                        {item.has_prompt_cache && (
                          <Badge variant="outline" className="text-[10px] h-5 cursor-pointer hover:bg-muted" onClick={(e) => loadPromptCache(item, e)}>提示词</Badge>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </CardContent>
        </Card>

        <Card className="xl:col-span-5 border-slate-200/80">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-2">
              <CardTitle className="text-base flex items-center gap-2">
                <Sparkles className="w-4 h-4" />
                生成结果
              </CardTitle>
              <div className="flex items-center gap-2">
                <select className="h-8 rounded-md border bg-background px-2 text-xs" value={selectedProduct} onChange={(e) => setSelectedProduct(e.target.value)}>
                  <option value="">全部产品</option>
                  {products.map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
                <Button size="sm" variant="ghost" className="h-8" onClick={refreshOutputs}>
                  <RefreshCw className="w-3.5 h-3.5" />
                </Button>
              </div>
            </div>
            <p className="text-xs text-muted-foreground break-all" title={gallerySource}>
              {gallerySource || "请在配置管理 → 路径配置中设置首图/主图文件夹"}
            </p>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3 max-h-[520px] overflow-auto pr-1">
              {filteredOutputs.length === 0 ? (
                <div className="col-span-full py-10 text-center text-xs text-muted-foreground">暂无生成图，点击「开始生成」运行任务</div>
              ) : (
                filteredOutputs.map((item) => (
                  <div key={item.path} className="rounded-xl border overflow-hidden bg-muted/10">
                    <div className="aspect-square bg-slate-100 flex items-center justify-center overflow-hidden">
                      {previewMap[item.path] ? (
                        <img src={previewMap[item.path]} alt={item.filename} className="w-full h-full object-cover" />
                      ) : (
                        <ImageIcon className="w-8 h-8 text-slate-300" />
                      )}
                    </div>
                    <div className="p-2 text-[10px] text-muted-foreground truncate" title={item.filename}>{item.filename}</div>
                  </div>
                ))
              )}
            </div>
          </CardContent>
        </Card>

        <Card className="xl:col-span-3 border-slate-200/80">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">运行日志</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-[520px] overflow-y-auto rounded-lg bg-slate-950 p-3 font-mono text-[11px] leading-relaxed">
              {logs.map((line, i) => (
                <div key={i} className="text-slate-300 mb-1">{line}</div>
              ))}
              <div ref={logEndRef} />
            </div>
          </CardContent>
        </Card>
      </div>

      <Dialog open={!!promptPreview} onOpenChange={(open) => !open && setPromptPreview(null)}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle>{promptPreview?.title}</DialogTitle>
          </DialogHeader>
          <pre className="flex-1 overflow-auto text-xs bg-slate-950 text-slate-200 p-4 rounded-lg whitespace-pre-wrap">{promptPreview?.text}</pre>
        </DialogContent>
      </Dialog>
    </div>
  );
}
