# -*- coding: utf-8 -*-
"""Generate AiImageGen.tsx with correct UTF-8 Chinese."""
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "frontend" / "client" / "src" / "pages" / "AiImageGen.tsx"

# Chinese labels as unicode escapes (encoding-safe in any editor)
L = {
    "doc": "AI \u751f\u56fe \u2014 \u6279\u91cf\u7535\u5546\u56fe\u751f\u6210\uff08Gemini \u51fa\u56fe + \u8c46\u5305\u7b56\u5212\uff09",
    "ready": "[\u5c31\u7eea] AI \u751f\u56fe\u5de5\u4f5c\u53f0\u5df2\u52a0\u8f7d",
    "load_fail": "\u52a0\u8f7d\u914d\u7f6e\u5931\u8d25",
    "save_ok": "\u914d\u7f6e\u5df2\u4fdd\u5b58",
    "save_fail": "\u4fdd\u5b58\u5931\u8d25",
    "start_ok": "AI \u751f\u56fe\u4efb\u52a1\u5df2\u542f\u52a8",
    "start_fail": "\u542f\u52a8\u5931\u8d25",
    "stop_ok": "\u5df2\u53d1\u9001\u505c\u6b62\u6307\u4ee4",
    "stop_fail": "\u505c\u6b62\u5931\u8d25",
    "status": "\u72b6\u6001",
    "img_mgmt": "\u56fe\u7247\u7ba1\u7406",
    "ai_gen": "AI \u751f\u56fe",
    "hero_desc": "\u6279\u91cf\u8bfb\u53d6\u539f\u56fe\u76ee\u5f55\uff0c\u8c46\u5305\u81ea\u52a8\u7b56\u5212\u63d0\u793a\u8bcd + Gemini \u751f\u6210\u7535\u5546\u98ce\u683c\u56fe\uff0c\u652f\u6301\u8df3\u8fc7\u5df2\u751f\u6210\u3001\u5e76\u53d1\u52a0\u901f\u3002",
    "running": "\u8fd0\u884c\u4e2d",
    "idle": "\u7a7a\u95f2",
    "settings": "\u8bbe\u7f6e",
    "stop": "\u505c\u6b62",
    "start": "\u5f00\u59cb\u751f\u6210",
    "gen_cfg": "\u751f\u6210\u914d\u7f6e\uff08\u5b8c\u6574\u539f\u811a\u672c\u53c2\u6570\uff09",
    "input_dir": "\u539f\u56fe\u76ee\u5f55",
    "output_dir": "\u8f93\u51fa\u76ee\u5f55",
    "gemini_key_ph": "\u6216\u73af\u5883\u53d8\u91cf GEMINI_API_KEY",
    "gemini_model": "Gemini \u6a21\u578b",
    "gemini_url": "Gemini Base URL",
    "per_image": "\u6bcf\u5f20\u539f\u56fe\u751f\u6210\u6570",
    "ratio_size": "\u5bbd\u9ad8\u6bd4 / \u5c3a\u5bf8",
    "workers": "\u5e76\u53d1 / \u63d0\u793a\u8bcd\u7ebf\u7a0b",
    "resize": "\u7f29\u56fe\u8fb9\u957f / JPEG \u8d28\u91cf",
    "global_pool": "\u5168\u5c40 Gemini \u7ebf\u7a0b\u6c60",
    "use_stream": "Gemini \u6d41\u5f0f\u63a5\u53e3",
    "skip_exist": "\u8df3\u8fc7\u5df2\u751f\u6210",
    "retry": "Gemini \u91cd\u8bd5 / \u95f4\u9694 / \u8bf7\u6c42\u95f4\u9694",
    "doubao_sec": "\u8c46\u5305\u7b56\u5212",
    "doubao_on": "\u542f\u7528\u8c46\u5305\u7b56\u5212",
    "doubao_key_label": "\u8c46\u5305 API Key",
    "doubao_key_ph": "\u6216\u73af\u5883\u53d8\u91cf ARK_API_KEY",
    "doubao_model": "\u8c46\u5305\u6a21\u578b / Base URL",
    "ep_file": "doubao_ep.txt \u8def\u5f84\uff08ep- \u63a5\u5165\u70b9\uff09",
    "ep_ph": "\u7559\u7a7a\u5219\u81ea\u52a8\u67e5\u627e",
    "out_lang": "\u8f93\u51fa\u8bed\u8a00",
    "probe": "\u542f\u52a8\u63a2\u6d4b",
    "probe_strict": "\u63a2\u6d4b\u5931\u8d25\u5373\u4e2d\u6b62",
    "cache_on": "\u7f13\u5b58\u63d0\u793a\u8bcd JSON",
    "use_cache": "\u4f18\u5148\u7528\u7f13\u5b58",
    "force_refresh": "\u5f3a\u5236\u5237\u65b0\u8c46\u5305\u7b56\u5212",
    "doubao_retry": "\u8c46\u5305\u91cd\u8bd5 / \u5ef6\u8fdf",
    "prompt_sec": "\u63d0\u793a\u8bcd\u7b56\u7565",
    "priority": "\u6765\u6e90\u4f18\u5148\u7ea7\uff08\u9017\u53f7\u5206\u9694\uff09",
    "user_req": "\u7528\u6237\u9700\u6c42\u63cf\u8ff0\uff08\u4f20\u7ed9\u8c46\u5305\uff09",
    "user_ph": "\u4e5f\u53ef\u5728\u539f\u56fe\u76ee\u5f55\u653e \u9700\u6c42.txt",
    "templates": "\u515c\u5e95\u4efb\u52a1\u7c7b\u578b\uff08\u6bcf\u884c\u4e00\u6761\uff09",
    "planner": "\u8c46\u5305\u7b56\u5212\u7cfb\u7edf\u6307\u4ee4\uff08DOUBAO_PLANNER_PROMPT\uff09",
    "save_btn": "\u4fdd\u5b58\u914d\u7f6e",
    "reload_btn": "\u91cd\u65b0\u52a0\u8f7d",
    "sources": "\u539f\u56fe\u7d20\u6750",
    "no_input_dir": "\u672a\u914d\u7f6e\u539f\u56fe\u76ee\u5f55",
    "no_inputs": "\u6682\u65e0\u539f\u56fe\uff0c\u8bf7\u68c0\u67e5\u539f\u56fe\u76ee\u5f55\u914d\u7f6e",
    "cache": "\u7f13\u5b58",
    "prompts": "\u63d0\u793a\u8bcd",
    "results": "\u751f\u6210\u7ed3\u679c",
    "all_products": "\u5168\u90e8\u4ea7\u54c1",
    "no_output_dir": "\u672a\u914d\u7f6e\u8f93\u51fa\u76ee\u5f55",
    "no_outputs": "\u6682\u65e0\u751f\u6210\u56fe\uff0c\u70b9\u51fb\u300c\u5f00\u59cb\u751f\u6210\u300d\u8fd0\u884c\u4efb\u52a1",
    "logs": "\u8fd0\u884c\u65e5\u5fd7",
    "no_prompt": "\u6682\u65e0\u63d0\u793a\u8bcd\u7f13\u5b58\uff0c\u8fd0\u884c\u540e\u4f1a\u751f\u6210 \u56fe\u540d_prompts.json",
    "prompt_title": " \u8c46\u5305\u63d0\u793a\u8bcd",
    "read_prompt_fail": "\u8bfb\u53d6\u63d0\u793a\u8bcd\u5931\u8d25",
}

tsx = r'''/**
 * {doc}
 */
import {{ useCallback, useEffect, useMemo, useRef, useState }} from "react";
import {{ Card, CardContent, CardHeader, CardTitle }} from "@/components/ui/card";
import {{ Button }} from "@/components/ui/button";
import {{ Input }} from "@/components/ui/input";
import {{ Label }} from "@/components/ui/label";
import {{ Badge }} from "@/components/ui/badge";
import {{ Textarea }} from "@/components/ui/textarea";
import {{ Switch }} from "@/components/ui/switch";
import {{
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
}} from "@/components/ui/dialog";
import {{ toast }} from "sonner";
import {{ imageApi, createLogSocket }} from "@/lib/api";
import {{
  ChevronRight,
  Play,
  Pause,
  RefreshCw,
  Sparkles,
  FolderOpen,
  ImageIcon,
  Wand2,
  Settings2,
}} from "lucide-react";

type InputItem = {{
  folder: string;
  folder_rel: string;
  image: string;
  image_path: string;
  has_txt: boolean;
  has_prompt_cache: boolean;
  prompt_cache_path?: string;
}};

type OutputItem = {{
  product: string;
  filename: string;
  path: string;
  size: number;
}};

export default function AiImageGen() {{
  const [running, setRunning] = useState(false);
  const [logs, setLogs] = useState<string[]>(["{ready}"]);
  const [config, setConfig] = useState<Record<string, any>>({{}});
  const [inputs, setInputs] = useState<InputItem[]>([]);
  const [outputs, setOutputs] = useState<OutputItem[]>([]);
  const [selectedProduct, setSelectedProduct] = useState<string>("");
  const [previewMap, setPreviewMap] = useState<Record<string, string>>({{}});
  const [showSettings, setShowSettings] = useState(false);
  const [promptPreview, setPromptPreview] = useState<{{ title: string; text: string }} | null>(null);
  const wsConnectedRef = useRef(false);

  const products = useMemo(() => {{
    const set = new Set<string>();
    inputs.forEach((x) => set.add(x.image.replace(/\\.[^.]+$/, "")));
    outputs.forEach((x) => set.add(x.product));
    return Array.from(set).sort();
  }}, [inputs, outputs]);

  const filteredOutputs = useMemo(() => {{
    if (!selectedProduct) return outputs;
    return outputs.filter((x) => x.product === selectedProduct);
  }}, [outputs, selectedProduct]);

  const loadConfig = async () => {{
    try {{
      const res: any = await imageApi.getAiGenConfig();
      const payload = res?.data ?? res;
      setConfig(payload?.data ?? payload ?? {{}});
    }} catch (e: any) {{
      toast.error(e.message || "{load_fail}");
    }}
  }};

  const saveConfig = async () => {{
    try {{
      const payload = {{ ...config }};
      if (payload.gemini_api_key === "***") delete payload.gemini_api_key;
      if (payload.doubao_api_key === "***") delete payload.doubao_api_key;
      if (typeof payload.prompt_templates === "string") {{
        payload.prompt_templates = (payload.prompt_templates as string)
          .split("\\n")
          .map((s) => s.trim())
          .filter(Boolean);
      }}
      if (typeof payload.prompt_source_priority === "string") {{
        payload.prompt_source_priority = (payload.prompt_source_priority as string)
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
      }}
      const res: any = await imageApi.updateAiGenConfig(payload);
      const body = res?.data ?? res;
      setConfig(body?.data ?? body ?? config);
      toast.success("{save_ok}");
    }} catch (e: any) {{
      toast.error(e.message || "{save_fail}");
    }}
  }};

  const refreshInputs = async () => {{
    try {{
      const res: any = await imageApi.getAiGenInputs();
      const payload = res?.data ?? res;
      setInputs(Array.isArray(payload?.data) ? payload.data : Array.isArray(payload) ? payload : []);
    }} catch {{
      setInputs([]);
    }}
  }};

  const refreshOutputs = async () => {{
    try {{
      const res: any = await imageApi.getAiGenOutputs(selectedProduct || undefined);
      const payload = res?.data ?? res;
      setOutputs(Array.isArray(payload?.data) ? payload.data : Array.isArray(payload) ? payload : []);
    }} catch {{
      setOutputs([]);
    }}
  }};

  const refreshStatus = async () => {{
    try {{
      const res: any = await imageApi.getAiGenStatus();
      const payload = res?.data ?? res;
      const status = payload?.data ?? payload;
      const isRunning = status?.status === "running" || status?.status === "stopping";
      setRunning(isRunning);
      if (status?.current_step) {{
        setLogs((prev) => {{
          const line = `[{status}] ${{status.current_step}}`;
          if (prev[prev.length - 1] === line) return prev;
          return [...prev, line].slice(-500);
        }});
      }}
      return status;
    }} catch {{
      return null;
    }}
  }};

  const handleStart = async () => {{
    try {{
      await saveConfig();
      await imageApi.startAiGen();
      setRunning(true);
      toast.success("{start_ok}");
      refreshStatus();
    }} catch (e: any) {{
      toast.error(e.message || "{start_fail}");
    }}
  }};

  const handleStop = async () => {{
    try {{
      await imageApi.stopAiGen();
      toast.info("{stop_ok}");
      refreshStatus();
    }} catch (e: any) {{
      toast.error(e.message || "{stop_fail}");
    }}
  }};

  const loadPreview = useCallback(async (path: string) => {{
    if (!path || previewMap[path]) return;
    try {{
      const res: any = await imageApi.getImageFileBlob(path);
      const blob = res?.data instanceof Blob ? res.data : res;
      if (blob instanceof Blob) {{
        const url = URL.createObjectURL(blob);
        setPreviewMap((prev) => ({{ ...prev, [path]: url }}));
      }}
    }} catch {{
      // ignore
    }}
  }}, [previewMap]);

  useEffect(() => {{
    loadConfig();
    refreshInputs();
    refreshOutputs();
    refreshStatus();
  }}, []);

  useEffect(() => {{
    refreshOutputs();
  }}, [selectedProduct]);

  useEffect(() => {{
    inputs.slice(0, 24).forEach((item) => loadPreview(item.image_path));
    filteredOutputs.slice(0, 36).forEach((item) => loadPreview(item.path));
  }}, [inputs, filteredOutputs, loadPreview]);

  useEffect(() => {{
    const timer = setInterval(() => {{
      refreshStatus().then((status) => {{
        if (!status) return;
        const done = ["completed", "failed", "idle"].includes(String(status.status || ""));
        if (done) {{
          refreshInputs();
          refreshOutputs();
        }}
      }});
    }}, running ? 1500 : 5000);
    return () => clearInterval(timer);
  }}, [running, selectedProduct]);

  useEffect(() => {{
    const ws = createLogSocket((data) => {{
      wsConnectedRef.current = true;
      const payload = data?.data || data;
      const moduleName = String(payload?.module || "");
      const msg = payload?.message || payload?.msg || payload?.text;
      if (!msg) return;
      if (moduleName && moduleName !== "ai_image_gen") return;
      setLogs((prev) => [...prev, String(msg)].slice(-500));
    }});
    return () => {{
      try {{
        ws?.close();
      }} catch {{
        // ignore
      }}
    }};
  }}, []);

  const loadPromptCache = async (item: InputItem, e?: React.MouseEvent) => {{
    e?.stopPropagation();
    try {{
      const res: any = await imageApi.getAiGenPrompts(item.image_path);
      const body = res?.data ?? res;
      const data = body?.data ?? body;
      const text = data?.exists
        ? JSON.stringify(data.data, null, 2)
        : "{no_prompt}";
      setPromptPreview({{ title: `${{item.image}}{prompt_title}`, text }});
    }} catch (err: any) {{
      toast.error(err.message || "{read_prompt_fail}");
    }}
  }};

  const setField = (key: string, value: any) => {{
    setConfig((prev) => ({{ ...prev, [key]: value }}));
  }};

  return (
    <div className="min-h-full p-8">
      <div className="relative overflow-hidden rounded-2xl border border-slate-800/60 bg-gradient-to-br from-slate-950 via-slate-900 to-indigo-950 p-8 mb-6">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_20%_20%,rgba(99,102,241,0.18),transparent_40%),radial-gradient(circle_at_80%_0%,rgba(14,165,233,0.12),transparent_35%)]" />
        <div className="relative z-10 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm text-slate-400 mb-2">
              <span>{img_mgmt}</span>
              <ChevronRight className="w-3.5 h-3.5" />
              <span className="text-slate-200">{ai_gen}</span>
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-white flex items-center gap-3">
              <Sparkles className="w-8 h-8 text-indigo-300" />
              Studio Genesis
            </h1>
            <p className="mt-2 max-w-2xl text-sm text-slate-300/90">{hero_desc}</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="border-indigo-400/40 text-indigo-200 bg-indigo-500/10">
              {{running ? "{running}" : "{idle}"}}
            </Badge>
            <Button size="sm" variant="outline" className="border-slate-600 text-slate-200 hover:bg-slate-800" onClick={{() => setShowSettings((v) => !v)}}>
              <Settings2 className="w-4 h-4 mr-1" />
              {settings}
            </Button>
            <Button size="sm" className="bg-indigo-500 hover:bg-indigo-400 text-white" onClick={{running ? handleStop : handleStart}}>
              {{running ? <Pause className="w-4 h-4 mr-1" /> : <Play className="w-4 h-4 mr-1" />}}
              {{running ? "{stop}" : "{start}"}}
            </Button>
          </div>
        </div>
      </div>

      {{showSettings && (
        <Card className="mb-6 border-slate-200/80 shadow-sm">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Wand2 className="w-4 h-4" />
              {gen_cfg}
            </CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 max-h-[70vh] overflow-y-auto pr-2">
            <div className="space-y-1.5">
              <Label className="text-xs">{input_dir}</Label>
              <Input value={{config.input_root_dir || ""}} onChange={{(e) => setField("input_root_dir", e.target.value)}} className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">{output_dir}</Label>
              <Input value={{config.output_root_dir || ""}} onChange={{(e) => setField("output_root_dir", e.target.value)}} className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">Gemini API Key</Label>
              <Input type="password" value={{config.gemini_api_key || ""}} onChange={{(e) => setField("gemini_api_key", e.target.value)}} placeholder="{gemini_key_ph}" className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">{gemini_model}</Label>
              <Input value={{config.gemini_model || ""}} onChange={{(e) => setField("gemini_model", e.target.value)}} className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">{gemini_url}</Label>
              <Input value={{config.gemini_base_url || ""}} onChange={{(e) => setField("gemini_base_url", e.target.value)}} className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">{per_image}</Label>
              <Input type="number" min={{1}} max={{20}} value={{config.generations_per_image ?? 6}} onChange={{(e) => setField("generations_per_image", Number(e.target.value))}} />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">{ratio_size}</Label>
              <div className="flex gap-2">
                <Input value={{config.aspect_ratio || "1:1"}} onChange={{(e) => setField("aspect_ratio", e.target.value)}} className="text-xs" />
                <Input value={{config.image_size || "1K"}} onChange={{(e) => setField("image_size", e.target.value)}} className="text-xs w-20" />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">{workers}</Label>
              <div className="flex gap-2">
                <Input type="number" min={{1}} value={{config.concurrent_workers ?? 5}} onChange={{(e) => setField("concurrent_workers", Number(e.target.value))}} className="text-xs" />
                <Input type="number" min={{1}} value={{config.prompt_workers ?? 2}} onChange={{(e) => setField("prompt_workers", Number(e.target.value))}} className="text-xs" />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">{resize}</Label>
              <div className="flex gap-2">
                <Input type="number" value={{config.resize_max_edge ?? 1280}} onChange={{(e) => setField("resize_max_edge", Number(e.target.value))}} className="text-xs" />
                <Input type="number" value={{config.jpeg_quality ?? 82}} onChange={{(e) => setField("jpeg_quality", Number(e.target.value))}} className="text-xs" />
              </div>
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">{global_pool}</Label>
              <Switch checked={{config.global_gemini_pool !== false}} onCheckedChange={{(v) => setField("global_gemini_pool", v)}} />
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">{use_stream}</Label>
              <Switch checked={{!!config.use_stream}} onCheckedChange={{(v) => setField("use_stream", v)}} />
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">{skip_exist}</Label>
              <Switch checked={{config.skip_existing !== false}} onCheckedChange={{(v) => setField("skip_existing", v)}} />
            </div>
            <div className="space-y-1.5 md:col-span-2">
              <Label className="text-xs">{retry}</Label>
              <div className="flex gap-2">
                <Input type="number" value={{config.max_retries ?? 3}} onChange={{(e) => setField("max_retries", Number(e.target.value))}} className="text-xs" />
                <Input type="number" value={{config.retry_delay ?? 6}} onChange={{(e) => setField("retry_delay", Number(e.target.value))}} className="text-xs" />
                <Input type="number" value={{config.request_interval ?? 0}} onChange={{(e) => setField("request_interval", Number(e.target.value))}} className="text-xs" />
              </div>
            </div>
            <div className="md:col-span-2 xl:col-span-3 text-xs font-semibold text-muted-foreground pt-2 border-t">{doubao_sec}</div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">{doubao_on}</Label>
              <Switch checked={{!!config.doubao_enabled}} onCheckedChange={{(v) => setField("doubao_enabled", v)}} />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">{doubao_key_label}</Label>
              <Input type="password" value={{config.doubao_api_key || ""}} onChange={{(e) => setField("doubao_api_key", e.target.value)}} placeholder="{doubao_key_ph}" className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5 md:col-span-2">
              <Label className="text-xs">{doubao_model}</Label>
              <div className="flex gap-2">
                <Input value={{config.doubao_model || ""}} onChange={{(e) => setField("doubao_model", e.target.value)}} className="text-xs font-mono" />
                <Input value={{config.doubao_base_url || ""}} onChange={{(e) => setField("doubao_base_url", e.target.value)}} className="text-xs font-mono" />
              </div>
            </div>
            <div className="space-y-1.5 md:col-span-2">
              <Label className="text-xs">{ep_file}</Label>
              <Input value={{config.doubao_ep_file || ""}} onChange={{(e) => setField("doubao_ep_file", e.target.value)}} placeholder="{ep_ph}" className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">{out_lang}</Label>
              <Input value={{config.doubao_output_language || "English"}} onChange={{(e) => setField("doubao_output_language", e.target.value)}} className="text-xs" />
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">{probe}</Label>
              <Switch checked={{config.doubao_probe_on_startup !== false}} onCheckedChange={{(v) => setField("doubao_probe_on_startup", v)}} />
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">{probe_strict}</Label>
              <Switch checked={{!!config.doubao_probe_strict}} onCheckedChange={{(v) => setField("doubao_probe_strict", v)}} />
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">{cache_on}</Label>
              <Switch checked={{config.cache_prompts !== false}} onCheckedChange={{(v) => setField("cache_prompts", v)}} />
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">{use_cache}</Label>
              <Switch checked={{config.use_cached_prompts !== false}} onCheckedChange={{(v) => setField("use_cached_prompts", v)}} />
            </div>
            <div className="flex items-center justify-between rounded-lg border px-3 py-2">
              <Label className="text-xs">{force_refresh}</Label>
              <Switch checked={{!!config.force_refresh}} onCheckedChange={{(v) => setField("force_refresh", v)}} />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">{doubao_retry}</Label>
              <div className="flex gap-2">
                <Input type="number" value={{config.doubao_max_retries ?? 3}} onChange={{(e) => setField("doubao_max_retries", Number(e.target.value))}} className="text-xs" />
                <Input type="number" value={{config.doubao_retry_delay ?? 5}} onChange={{(e) => setField("doubao_retry_delay", Number(e.target.value))}} className="text-xs" />
              </div>
            </div>
            <div className="md:col-span-2 xl:col-span-3 text-xs font-semibold text-muted-foreground pt-2 border-t">{prompt_sec}</div>
            <div className="space-y-1.5 md:col-span-2 xl:col-span-3">
              <Label className="text-xs">{priority}</Label>
              <Input value={{Array.isArray(config.prompt_source_priority) ? config.prompt_source_priority.join(", ") : "cache, doubao, txt"}} onChange={{(e) => setField("prompt_source_priority", e.target.value)}} className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5 md:col-span-2 xl:col-span-3">
              <Label className="text-xs">{user_req}</Label>
              <Textarea rows={{3}} value={{config.user_requirement || ""}} onChange={{(e) => setField("user_requirement", e.target.value)}} placeholder="{user_ph}" className="text-xs" />
            </div>
            <div className="space-y-1.5 md:col-span-2 xl:col-span-3">
              <Label className="text-xs">{templates}</Label>
              <Textarea rows={{2}} value={{Array.isArray(config.prompt_templates) ? config.prompt_templates.join("\\n") : ""}} onChange={{(e) => setField("prompt_templates", e.target.value)}} className="text-xs font-mono" />
            </div>
            <div className="space-y-1.5 md:col-span-2 xl:col-span-3">
              <Label className="text-xs">{planner}</Label>
              <Textarea rows={{10}} value={{config.doubao_planner_prompt || ""}} onChange={{(e) => setField("doubao_planner_prompt", e.target.value)}} className="text-xs font-mono leading-relaxed" />
            </div>
            <div className="md:col-span-2 xl:col-span-3 flex gap-2 pb-2">
              <Button size="sm" onClick={{saveConfig}}>{save_btn}</Button>
              <Button size="sm" variant="outline" onClick={{loadConfig}}>{reload_btn}</Button>
            </div>
          </CardContent>
        </Card>
      )}}

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
        <Card className="xl:col-span-4 border-slate-200/80">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <FolderOpen className="w-4 h-4" />
                {sources}
              </CardTitle>
              <Button size="sm" variant="ghost" className="h-8" onClick={{refreshInputs}}>
                <RefreshCw className="w-3.5 h-3.5" />
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">{{config.input_root_dir || "{no_input_dir}"}}</p>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-3 max-h-[520px] overflow-auto pr-1">
              {{inputs.length === 0 ? (
                <div className="col-span-2 py-10 text-center text-xs text-muted-foreground">{no_inputs}</div>
              ) : (
                inputs.map((item) => (
                  <div key={{item.image_path}} className="rounded-xl border bg-muted/20 overflow-hidden hover:border-indigo-300 cursor-pointer" onClick={{() => setSelectedProduct(item.image.replace(/\\.[^.]+$/, ""))}}>
                    <div className="aspect-square bg-slate-100 flex items-center justify-center overflow-hidden">
                      {{previewMap[item.image_path] ? (
                        <img src={{previewMap[item.image_path]}} alt={{item.image}} className="w-full h-full object-cover" />
                      ) : (
                        <ImageIcon className="w-8 h-8 text-slate-300" />
                      )}}
                    </div>
                    <div className="p-2 space-y-1">
                      <div className="text-[11px] font-medium truncate" title={{item.image}}>{{item.image}}</div>
                      <div className="flex gap-1 flex-wrap">
                        {{item.has_txt && <Badge variant="secondary" className="text-[10px] h-5">txt</Badge>}}
                        {{item.has_prompt_cache && (
                          <Badge variant="outline" className="text-[10px] h-5 cursor-pointer hover:bg-muted" onClick={{(e) => loadPromptCache(item, e)}}>{prompts}</Badge>
                        )}}
                      </div>
                    </div>
                  </div>
                ))
              )}}
            </div>
          </CardContent>
        </Card>

        <Card className="xl:col-span-5 border-slate-200/80">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between gap-2">
              <CardTitle className="text-base flex items-center gap-2">
                <Sparkles className="w-4 h-4" />
                {results}
              </CardTitle>
              <div className="flex items-center gap-2">
                <select className="h-8 rounded-md border bg-background px-2 text-xs" value={{selectedProduct}} onChange={{(e) => setSelectedProduct(e.target.value)}}>
                  <option value="">{all_products}</option>
                  {{products.map((p) => (
                    <option key={{p}} value={{p}}>{{p}}</option>
                  ))}}
                </select>
                <Button size="sm" variant="ghost" className="h-8" onClick={{refreshOutputs}}>
                  <RefreshCw className="w-3.5 h-3.5" />
                </Button>
              </div>
            </div>
            <p className="text-xs text-muted-foreground">{{config.output_root_dir || "{no_output_dir}"}}</p>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3 max-h-[520px] overflow-auto pr-1">
              {{filteredOutputs.length === 0 ? (
                <div className="col-span-full py-10 text-center text-xs text-muted-foreground">{no_outputs}</div>
              ) : (
                filteredOutputs.map((item) => (
                  <div key={{item.path}} className="rounded-xl border overflow-hidden bg-muted/10">
                    <div className="aspect-square bg-slate-100 flex items-center justify-center overflow-hidden">
                      {{previewMap[item.path] ? (
                        <img src={{previewMap[item.path]}} alt={{item.filename}} className="w-full h-full object-cover" />
                      ) : (
                        <ImageIcon className="w-8 h-8 text-slate-300" />
                      )}}
                    </div>
                    <div className="p-2 text-[10px] text-muted-foreground truncate" title={{item.filename}}>{{item.filename}}</div>
                  </div>
                ))
              )}}
            </div>
          </CardContent>
        </Card>

        <Card className="xl:col-span-3 border-slate-200/80">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{logs}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-[520px] overflow-y-auto rounded-lg bg-slate-950 p-3 font-mono text-[11px] leading-relaxed">
              {{logs.map((line, i) => (
                <div key={{i}} className="text-slate-300 mb-1">{{line}}</div>
              ))}}
            </div>
          </CardContent>
        </Card>
      </div>

      <Dialog open={{!!promptPreview}} onOpenChange={{(open) => !open && setPromptPreview(null)}}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle>{{promptPreview?.title}}</DialogTitle>
          </DialogHeader>
          <pre className="flex-1 overflow-auto text-xs bg-slate-950 text-slate-200 p-4 rounded-lg whitespace-pre-wrap">{{promptPreview?.text}}</pre>
        </DialogContent>
      </Dialog>
    </div>
  );
}}
'''

# Fix doubao key label hack - use proper key
L["doubao_key_label"] = "\u8c46\u5305 API Key"

out_text = tsx.format(**L)

OUT.write_text(out_text, encoding="utf-8")
text = OUT.read_text(encoding="utf-8")
assert "\u56fe\u7247\u7ba1\u7406" in text
assert "???" not in text or text.count("???") < 3
print("written", OUT, "chars", len(text))
