/**
 * PublishPageScanner - 发品页面元素扫描（独立工具页）
 */
import { useMemo, useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "sonner";
import { pageScanApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  ScanSearch,
  Loader2,
  LayoutGrid,
  List,
  Download,
  CheckCircle2,
  XCircle,
  Workflow,
  Link2,
} from "lucide-react";

const DEFAULT_PAGE_LINES = `复制发品|https://post.alibaba.com/product/publish.htm?spm=a2747.product_manager.0.0.65f771d2VPmQiz&pubType=similarPost&itemId=1601212500292&behavior=copyNew`;

const PAGE_SCAN_CACHE_KEY = "publish_page_scanner_cache";

type PageScanCache = {
  pageLines: string;
  probeButtons: boolean;
  batch: BatchScanResult | null;
  selectedIndex: number;
  logs: string[];
  groupName: string;
  syncPlatform: boolean;
  applyReport: {
    ready_for_publish?: boolean;
    readiness_issues?: string[];
    field_requirements?: Array<{
      label: string;
      config_key: string;
      category: string;
      configured: boolean;
      required: boolean;
    }>;
    compliance_fields?: Array<{
      label: string;
      struct_id?: string;
      source?: string;
      required?: boolean;
    }>;
  } | null;
  updatedAt: number;
};

function readPageScanCache(): PageScanCache | null {
  try {
    const raw = sessionStorage.getItem(PAGE_SCAN_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PageScanCache;
    if (parsed?.batch && !Array.isArray(parsed.batch.pages)) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function writePageScanCache(patch: Partial<Omit<PageScanCache, "updatedAt">>) {
  try {
    const prev = readPageScanCache() || {
      pageLines: DEFAULT_PAGE_LINES,
      probeButtons: true,
      batch: null,
      selectedIndex: 0,
      logs: [],
      groupName: "",
      syncPlatform: true,
      applyReport: null,
      updatedAt: 0,
    };
    sessionStorage.setItem(
      PAGE_SCAN_CACHE_KEY,
      JSON.stringify({ ...prev, ...patch, updatedAt: Date.now() }),
    );
  } catch {
    // sessionStorage 配额不足时忽略（扫描结果过大时仍可当次使用）
  }
}

function clearPageScanCache() {
  try {
    sessionStorage.removeItem(PAGE_SCAN_CACHE_KEY);
  } catch {
    // ignore
  }
}

type ScanElement = {
  id: string;
  category: string;
  label: string;
  text: string;
  value?: string;
  selector: string;
  rect: { x: number; y: number; width: number; height: number };
  source?: string;
  tag?: string;
  disabled?: boolean;
};

type ScanSection = {
  id: string;
  title: string;
  y_start: number;
  elements: ScanElement[];
};

type WorkflowStep = {
  step: number;
  action: string;
  detail?: string;
  selector?: string;
  options?: string[];
  operable?: boolean;
  clicked?: boolean;
  available?: boolean;
  rows?: string;
  new_row?: boolean;
  reveals_upload?: boolean;
  file_inputs?: string;
  interaction?: string;
  error?: string;
};

type PageWorkflow = {
  id: string;
  title: string;
  type: string;
  operable?: boolean;
  steps: WorkflowStep[];
  upload_methods?: string[];
  local_upload?: Record<string, string>;
  photobank?: Record<string, unknown>;
  switch_note?: string;
  add_row_note?: string;
  automation_module?: string;
  automation_hint?: string;
  spec_name?: string;
  interaction?: string;
  struct_id?: string;
  attribute_count?: number;
  attribute_samples?: string[];
  fields?: string[];
  error?: string;
};

type ScanResult = {
  url: string;
  title: string;
  element_count: number;
  categories: Record<string, number>;
  elements: ScanElement[];
  sections: ScanSection[];
  scroll?: { width: number; height: number };
  probe_log?: { button: string; new_elements: string }[];
  workflows?: PageWorkflow[];
  workflow_count?: number;
  duration_seconds?: number;
  logs?: string[];
};

type PageScanItem = ScanResult & {
  name: string;
  page_type?: string;
  page_type_label?: string;
  success: boolean;
  error?: string;
};

type BatchScanResult = {
  total: number;
  succeeded: number;
  failed: number;
  pages: PageScanItem[];
  duration_seconds?: number;
  logs?: string[];
};

function parsePageLines(text: string): { name?: string; url: string }[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"))
    .map((line, index) => {
      const pipe = line.indexOf("|");
      if (pipe > 0) {
        return { name: line.slice(0, pipe).trim(), url: line.slice(pipe + 1).trim() };
      }
      const tab = line.indexOf("\t");
      if (tab > 0) {
        return { name: line.slice(0, tab).trim(), url: line.slice(tab + 1).trim() };
      }
      return { name: `页面 ${index + 1}`, url: line };
    })
    .filter((item) => item.url.startsWith("http"));
}

const CATEGORY_STYLE: Record<string, string> = {
  input: "bg-blue-500/15 border-blue-400 text-blue-900",
  textarea: "bg-blue-500/15 border-blue-400 text-blue-900",
  select: "bg-violet-500/15 border-violet-400 text-violet-900",
  button: "bg-amber-500/15 border-amber-400 text-amber-900",
  upload: "bg-emerald-500/15 border-emerald-400 text-emerald-900",
  checkbox: "bg-slate-500/15 border-slate-400",
  radio: "bg-slate-500/15 border-slate-400",
  switch: "bg-cyan-500/15 border-cyan-400",
  tab: "bg-indigo-500/15 border-indigo-400",
  other: "bg-gray-500/10 border-gray-300",
};

function categoryClass(cat: string) {
  return CATEGORY_STYLE[cat] || CATEGORY_STYLE.other;
}

function LayoutPreview({ result }: { result: ScanResult }) {
  const pageW = Math.max(result.scroll?.width || 1200, 800);
  const pageH = Math.max(result.scroll?.height || 2000, 1200);
  const scale = 0.45;

  return (
    <div className="overflow-auto rounded-lg border bg-muted/30 p-4">
      <div
        className="relative mx-auto bg-white shadow-sm"
        style={{ width: pageW * scale, height: pageH * scale }}
      >
        <div
          className="absolute left-0 top-0 origin-top-left"
          style={{ width: pageW, height: pageH, transform: `scale(${scale})` }}
        >
          {result.elements.map((el) => (
            <div
              key={el.id}
              title={`${el.category}: ${el.label || el.text}\n${el.selector}`}
              className={`absolute overflow-hidden rounded border text-[10px] leading-tight ${categoryClass(el.category)}`}
              style={{
                left: el.rect.x,
                top: el.rect.y,
                width: Math.max(el.rect.width, 24),
                height: Math.max(el.rect.height, 18),
              }}
            >
              <span className="block truncate px-0.5 py-0.5">
                {el.label || el.text || el.category}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function WorkflowCard({ wf }: { wf: PageWorkflow }) {
  const typeLabel: Record<string, string> = {
    form_field: "表单",
    attributes: "属性",
    spec_attribute: "规格",
    image_upload: "图片",
    sku: "SKU",
    compliance: "合规",
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-base">{wf.title}</CardTitle>
          <Badge variant={wf.operable ? "default" : "secondary"}>
            {wf.operable ? "可操作" : "待确认"}
          </Badge>
          {wf.type ? (
            <Badge variant="outline" className="text-[10px]">
              {typeLabel[wf.type] ?? wf.type}
            </Badge>
          ) : null}
          {wf.interaction ? (
            <Badge variant="outline" className="text-[10px]">
              {wf.interaction === "checkbox_grid" ? "复选框网格" : "规格行"}
            </Badge>
          ) : null}
          {wf.automation_module ? (
            <Badge variant="outline" className="font-mono text-[10px]">
              {wf.automation_module}
            </Badge>
          ) : null}
        </div>
        {wf.struct_id ? (
          <p className="font-mono text-[11px] text-muted-foreground">#{wf.struct_id}</p>
        ) : null}
        {wf.attribute_count != null ? (
          <p className="text-xs text-muted-foreground">
            共 {wf.attribute_count} 个属性
            {wf.attribute_samples?.length
              ? ` · 示例：${wf.attribute_samples.join("、")}`
              : null}
          </p>
        ) : null}
        {wf.fields?.length ? (
          <p className="text-xs text-muted-foreground">合规字段：{wf.fields.join("、")}</p>
        ) : null}
        {wf.switch_note ? (
          <p className="text-xs text-muted-foreground">{wf.switch_note}</p>
        ) : null}
        {wf.add_row_note ? (
          <p className="text-xs text-muted-foreground">{wf.add_row_note}</p>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-3">
        {wf.upload_methods && wf.upload_methods.length > 0 ? (
          <div className="text-sm">
            <span className="font-medium">上传方式：</span>
            {wf.upload_methods.join(" / ")}
          </div>
        ) : null}
        <ol className="space-y-2 text-sm">
          {wf.steps.map((s) => (
            <li key={s.step} className="rounded-md border bg-muted/30 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">
                  {s.step}. {s.action}
                </span>
                {s.operable === true ? (
                  <Badge variant="outline" className="text-emerald-700">
                    已验证
                  </Badge>
                ) : null}
                {s.operable === false ? (
                  <Badge variant="outline" className="text-amber-700">
                    未验证
                  </Badge>
                ) : null}
              </div>
              {s.detail ? <p className="mt-1 text-muted-foreground">{s.detail}</p> : null}
              {s.options?.length ? (
                <p className="mt-1">选项：{s.options.join("、")}</p>
              ) : null}
              {s.selector ? (
                <p className="mt-1 font-mono text-[11px] break-all text-muted-foreground">
                  选择器: {s.selector}
                </p>
              ) : null}
              {s.rows ? <p className="mt-1 text-xs">行数变化: {s.rows}</p> : null}
              {s.file_inputs ? <p className="mt-1 text-xs">file input: {s.file_inputs}</p> : null}
              {s.error ? <p className="mt-1 text-xs text-destructive">{s.error}</p> : null}
            </li>
          ))}
        </ol>
        {wf.automation_hint ? (
          <p className="rounded border border-dashed p-2 text-xs text-muted-foreground">
            自动发品对接：{wf.automation_hint}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ElementRow({ el }: { el: ScanElement }) {
  return (
    <div className="rounded-md border bg-card p-3 text-sm">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <Badge variant="outline" className={categoryClass(el.category)}>
          {el.category}
        </Badge>
        {el.source === "static" ? null : (
          <Badge variant="secondary">探测发现</Badge>
        )}
        {el.disabled ? <Badge variant="destructive">禁用</Badge> : null}
      </div>
      <div className="font-medium">{el.label || el.text || "(无标签)"}</div>
      {el.value ? (
        <div className="mt-1 text-xs text-muted-foreground">当前值: {el.value}</div>
      ) : null}
      <div className="mt-1 font-mono text-[11px] text-muted-foreground break-all">{el.selector}</div>
      <div className="mt-1 text-[11px] text-muted-foreground">
        位置: ({el.rect.x}, {el.rect.y}) {el.rect.width}×{el.rect.height}
      </div>
    </div>
  );
}

function unwrapBatchResult(res: unknown): BatchScanResult {
  const body = res as { data?: BatchScanResult } | BatchScanResult;
  const data =
    body && typeof body === "object" && "data" in body && body.data
      ? body.data
      : (body as BatchScanResult);
  if (!data || !Array.isArray(data.pages)) {
    throw new Error("扫描返回数据格式异常，请确认后端已更新并重启");
  }
  return data;
}

export default function PublishPageScanner() {
  const initialCache = readPageScanCache();

  const [pageLines, setPageLines] = useState(initialCache?.pageLines ?? DEFAULT_PAGE_LINES);
  const [probeButtons, setProbeButtons] = useState(initialCache?.probeButtons ?? true);
  const [scanning, setScanning] = useState(false);
  const [batch, setBatch] = useState<BatchScanResult | null>(initialCache?.batch ?? null);
  const [selectedIndex, setSelectedIndex] = useState(initialCache?.selectedIndex ?? 0);
  const [logs, setLogs] = useState<string[]>(initialCache?.logs?.length ? initialCache.logs : []);
  const [groupName, setGroupName] = useState(initialCache?.groupName ?? "");
  const [syncPlatform, setSyncPlatform] = useState(initialCache?.syncPlatform ?? true);
  const [applying, setApplying] = useState(false);
  const [applyReport, setApplyReport] = useState<{
    ready_for_publish?: boolean;
    readiness_issues?: string[];
    field_requirements?: Array<{
      label: string;
      config_key: string;
      category: string;
      configured: boolean;
      required: boolean;
    }>;
    compliance_fields?: Array<{
      label: string;
      struct_id?: string;
      source?: string;
      required?: boolean;
    }>;
  } | null>(initialCache?.applyReport ?? null);

  const result = batch?.pages[selectedIndex]?.success ? batch.pages[selectedIndex] : null;

  useEffect(() => {
    writePageScanCache({
      pageLines,
      probeButtons,
      batch,
      selectedIndex,
      logs,
      groupName,
      syncPlatform,
      applyReport,
    });
  }, [pageLines, probeButtons, batch, selectedIndex, logs, groupName, syncPlatform, applyReport]);

  useEffect(() => {
    if (initialCache?.batch?.pages?.length) {
      toast.info("已恢复上次扫描结果（切换页面不会丢失）", { duration: 3500 });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (result?.name) {
      setGroupName(result.name);
    }
  }, [result?.name]);

  const categoryEntries = useMemo(
    () => (result ? Object.entries(result.categories).sort((a, b) => b[1] - a[1]) : []),
    [result],
  );

  const handleScan = async () => {
    const pages = parsePageLines(pageLines);
    if (pages.length === 0) {
      toast.error("请至少输入一个有效 URL（每行一个，可用「名称|URL」格式）");
      return;
    }
    if (pages.length > 20) {
      toast.error("单次最多扫描 20 个页面");
      return;
    }

    setScanning(true);
    setBatch(null);
    setSelectedIndex(0);
    setApplyReport(null);
    setLogs([`[扫描] 批量任务启动，共 ${pages.length} 个页面…`]);
    try {
      const res = await pageScanApi.scanBatch({
        pages,
        probe_buttons: probeButtons,
        wait_seconds: 45,
      });
      const data = unwrapBatchResult(res);
      setBatch(data);
      setLogs(data.logs?.length ? data.logs : ["[扫描] 完成"]);
      const firstOk = data.pages.findIndex((p) => p.success);
      setSelectedIndex(firstOk >= 0 ? firstOk : 0);
      toast.success(`批量扫描完成：成功 ${data.succeeded}/${data.total}`);
    } catch (err: unknown) {
      const axiosErr = err as { response?: { status?: number; data?: { detail?: string } } };
      const status = axiosErr?.response?.status;
      let msg =
        axiosErr?.response?.data?.detail ||
        (err as Error)?.message ||
        "扫描失败";
      if (status === 405 || /method not allowed/i.test(String(msg))) {
        msg =
          "后端未加载发品页扫描接口（Method Not Allowed）。请重启 backend 服务（端口 8000）后再试。";
      }
      setLogs((prev) => [...prev, `[错误] ${msg}`]);
      toast.error(String(msg));
    } finally {
      setScanning(false);
    }
  };

  const handleExport = () => {
    if (!batch) return;
    const blob = new Blob([JSON.stringify(batch, null, 2)], { type: "application/json" });
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = `page-scan-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.json`;
    a.click();
    URL.revokeObjectURL(objectUrl);
    toast.success("已导出 JSON");
  };

  const handleClearResults = () => {
    setBatch(null);
    setSelectedIndex(0);
    setLogs([]);
    setApplyReport(null);
    clearPageScanCache();
    toast.success("已清除扫描结果");
  };

  const handleApplyToConfig = async () => {
    if (!result) return;
    const group = groupName.trim();
    if (!group) {
      toast.error("请填写组别名称（与首图文件名中的组别一致）");
      return;
    }
    const pageUrl = result.url || parsePageLines(pageLines).find((p) => p.name === result.name)?.url;
    if (!pageUrl) {
      toast.error("无法确定发品页 URL");
      return;
    }

    setApplying(true);
    setApplyReport(null);
    setLogs((prev) => [...prev, `[对接] 正在应用到产品配置：组别=${group}…`]);
    try {
      const res = await pageScanApi.applyToConfig({
        group_name: group,
        url: pageUrl,
        workflows: result.workflows || [],
        page_type: result.page_type,
        page_type_label: result.page_type_label,
        element_count: result.element_count,
        workflow_count: result.workflow_count ?? result.workflows?.length,
        sync_platform: syncPlatform,
      });
      const body = res as unknown as { data?: Record<string, unknown> };
      const data = body?.data ?? (res as unknown as Record<string, unknown>);
      const ready = Boolean(data?.ready_for_publish);
      const issues = (data?.readiness_issues as string[]) || [];
      const fieldReqs =
        (data?.field_requirements as Array<{
          label: string;
          config_key: string;
          category: string;
          configured: boolean;
          required: boolean;
        }>) || [];
      const complianceFields =
        (data?.compliance_fields as Array<{
          label: string;
          struct_id?: string;
          source?: string;
          required?: boolean;
        }>) || [];
      setApplyReport({
        ready_for_publish: ready,
        readiness_issues: issues,
        field_requirements: fieldReqs,
        compliance_fields: complianceFields,
      });
      const syncLogs = (data?.logs as string[]) || [];
      setLogs((prev) => [...prev, ...syncLogs.map((l) => `[对接] ${l}`)]);
      if (ready) {
        toast.success("已对接产品配置，该组别可自动发品");
      } else {
        toast.warning(`已写入配置，尚有 ${issues.length} 项待完善`);
      }
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        || (err as Error)?.message
        || "对接失败";
      setLogs((prev) => [...prev, `[对接错误] ${msg}`]);
      toast.error(String(msg));
    } finally {
      setApplying(false);
    }
  };

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">发品页面元素扫描</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          自动识别发品页元素，并生成「功能地图」（本地上传、规格图开关、+添加等操作流程）。功能地图每次扫描都会生成。
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ScanSearch className="h-4 w-4" />
            扫描配置
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>页面列表（每行一个）</Label>
            <Textarea
              value={pageLines}
              onChange={(e) => setPageLines(e.target.value)}
              rows={6}
              className="font-mono text-xs"
              placeholder={"复制发品|https://post.alibaba.com/...\\n新发品|https://post.alibaba.com/...\\n# 以 # 开头的行为注释"}
            />
            <p className="text-xs text-muted-foreground">
              格式：<code className="rounded bg-muted px-1">页面名称|URL</code>，或直接粘贴 URL。单次最多 20 页。
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Switch id="probe" checked={probeButtons} onCheckedChange={setProbeButtons} />
            <Label htmlFor="probe">额外探测（点击「添加/展开」等按钮，发现更多隐藏元素）</Label>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={handleScan} disabled={scanning}>
              {scanning ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  批量扫描中…
                </>
              ) : (
                "开始批量扫描"
              )}
            </Button>
            <Button variant="outline" onClick={handleExport} disabled={!batch || scanning}>
              <Download className="mr-2 h-4 w-4" />
              导出全部 JSON
            </Button>
            <Button variant="outline" onClick={handleClearResults} disabled={!batch || scanning}>
              清除结果
            </Button>
          </div>
          {scanning ? (
            <p className="text-xs text-amber-700">
              将弹出 Chrome 并依次扫描各页面。首次需登录阿里账号，后续页面复用会话。每页约 30–90 秒。
            </p>
          ) : null}
        </CardContent>
      </Card>

      {logs.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">扫描日志</CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-28 rounded border bg-muted/40 p-3 font-mono text-xs">
              {logs.map((line, i) => (
                <div key={i}>{line}</div>
              ))}
            </ScrollArea>
          </CardContent>
        </Card>
      ) : null}

      {batch ? (
        <div className="flex flex-col gap-4 lg:flex-row">
          <Card className="lg:w-72 shrink-0">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">扫描结果</CardTitle>
              <p className="text-xs text-muted-foreground">
                成功 {batch.succeeded}/{batch.total} · 总耗时 {batch.duration_seconds}s
              </p>
            </CardHeader>
            <CardContent className="p-0">
              <ScrollArea className="h-[min(480px,60vh)]">
                <div className="space-y-1 p-3 pt-0">
                  {batch.pages.map((page, index) => (
                    <button
                      key={`${page.name}-${index}`}
                      type="button"
                      onClick={() => setSelectedIndex(index)}
                      className={cn(
                        "w-full rounded-md border px-3 py-2 text-left text-sm transition-colors",
                        selectedIndex === index
                          ? "border-primary bg-primary/5"
                          : "border-transparent hover:bg-muted/60",
                      )}
                    >
                      <div className="flex items-start gap-2">
                        {page.success ? (
                          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                        ) : (
                          <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
                        )}
                        <div className="min-w-0 flex-1">
                          <div className="truncate font-medium">{page.name}</div>
                          <div className="truncate text-xs text-muted-foreground">
                            {page.page_type_label || page.page_type || "未知类型"}
                          </div>
                          {page.success ? (
                            <div className="text-xs text-muted-foreground">{page.element_count} 个元素</div>
                          ) : (
                            <div className="truncate text-xs text-destructive">{page.error}</div>
                          )}
                        </div>
                      </div>
                    </button>
                  ))}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>

          <div className="min-w-0 flex-1 space-y-4">
            {!result ? (
              <Card>
                <CardContent className="py-10 text-center text-sm text-muted-foreground">
                  当前选中的页面扫描失败，请查看左侧错误信息或重新扫描。
                </CardContent>
              </Card>
            ) : (
              <>
                <div className="flex flex-wrap gap-2">
                  <Badge variant="secondary">{result.name}</Badge>
                  <Badge variant="outline">{result.page_type_label}</Badge>
                  <Badge variant="secondary">元素 {result.element_count}</Badge>
                  <Badge variant="outline">耗时 {result.duration_seconds}s</Badge>
                  {applyReport?.ready_for_publish ? (
                    <Badge className="bg-emerald-600">已对接 · 可发品</Badge>
                  ) : applyReport ? (
                    <Badge variant="destructive">已对接 · 待完善</Badge>
                  ) : null}
                  {categoryEntries.map(([cat, n]) => (
                    <Badge key={cat} variant="outline">
                      {cat}: {n}
                    </Badge>
                  ))}
                </div>

                <Card>
                  <CardHeader className="pb-2">
                    <CardTitle className="flex items-center gap-2 text-base">
                      <Link2 className="h-4 w-4" />
                      对接自动发品
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <p className="text-xs text-muted-foreground">
                      将本页扫描结果写入产品配置：绑定组别发品链接、保存功能地图档案，并可从平台同步属性/规格。
                    </p>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div className="space-y-1">
                        <Label className="text-xs">组别名称</Label>
                        <Input
                          value={groupName}
                          onChange={(e) => setGroupName(e.target.value)}
                          placeholder="与首图文件名组别段一致"
                        />
                      </div>
                      <div className="flex items-end gap-3 pb-1">
                        <Switch id="sync-platform" checked={syncPlatform} onCheckedChange={setSyncPlatform} />
                        <Label htmlFor="sync-platform" className="text-xs">
                          从平台同步属性/规格（推荐）
                        </Label>
                      </div>
                    </div>
                    <Button onClick={handleApplyToConfig} disabled={applying || scanning}>
                      {applying ? (
                        <>
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                          对接中…
                        </>
                      ) : (
                        "应用到产品配置"
                      )}
                    </Button>
                    {applyReport?.field_requirements?.length ? (
                      <div className="rounded-md border bg-muted/40 p-3 text-xs">
                        <p className="mb-2 font-medium text-foreground">必填 / 上传项配置清单</p>
                        <ul className="space-y-1">
                          {applyReport.field_requirements.map((req) => (
                            <li key={`${req.config_key}-${req.label}`} className="flex flex-wrap items-center gap-2">
                              <span
                                className={cn(
                                  "inline-block h-2 w-2 rounded-full",
                                  req.configured ? "bg-emerald-500" : "bg-amber-500",
                                )}
                              />
                              <span>{req.label}</span>
                              <Badge variant="outline" className="text-[10px]">
                                {req.category === "upload" ? "路径" : req.category}
                              </Badge>
                              <code className="text-[10px] text-muted-foreground">{req.config_key}</code>
                              {req.configured ? (
                                <span className="text-emerald-700">已配置</span>
                              ) : req.required ? (
                                <span className="text-amber-800">待配置</span>
                              ) : (
                                <span className="text-muted-foreground">可选</span>
                              )}
                            </li>
                          ))}
                        </ul>
                        <p className="mt-2 text-muted-foreground">
                          上传类请在「路径配置」填写目录；卖点等文本类在详情配置中设置。自动发品会按模块写入对应位置。
                        </p>
                      </div>
                    ) : null}
                    {applyReport?.compliance_fields?.length ? (
                      <div className="rounded-md border border-dashed p-3 text-xs">
                        <p className="mb-2 font-medium">本页合规必填（动态扫描，跨类目）</p>
                        <ul className="space-y-1">
                          {applyReport.compliance_fields.map((cf) => (
                            <li key={cf.label} className="flex flex-wrap gap-2">
                              <span>{cf.label}</span>
                              {cf.struct_id ? (
                                <code className="text-[10px] text-muted-foreground">{cf.struct_id}</code>
                              ) : null}
                              <Badge variant="outline" className="text-[10px]">
                                {cf.source || "scan"}
                              </Badge>
                            </li>
                          ))}
                        </ul>
                        <p className="mt-2 text-muted-foreground">
                          发品时无正式配置将临时用 a（文本）或 1（数字）占位验收。
                        </p>
                      </div>
                    ) : null}
                    {applyReport?.readiness_issues?.length ? (
                      <ul className="list-inside list-disc text-xs text-amber-800">
                        {applyReport.readiness_issues.map((issue) => (
                          <li key={issue}>{issue}</li>
                        ))}
                      </ul>
                    ) : null}
                  </CardContent>
                </Card>

                <Tabs defaultValue="workflows">
                  <TabsList>
                    <TabsTrigger value="workflows" className="gap-1">
                      <Workflow className="h-3.5 w-3.5" />
                      功能地图
                      {result.workflow_count ? ` (${result.workflow_count})` : ""}
                    </TabsTrigger>
                    <TabsTrigger value="layout" className="gap-1">
                      <LayoutGrid className="h-3.5 w-3.5" />
                      排版视图
                    </TabsTrigger>
                    <TabsTrigger value="sections" className="gap-1">
                      <List className="h-3.5 w-3.5" />
                      分区列表
                    </TabsTrigger>
                    <TabsTrigger value="all">全部元素</TabsTrigger>
                  </TabsList>

                  <TabsContent value="workflows" className="mt-4 space-y-4">
                    {result.workflows && result.workflows.length > 0 ? (
                      result.workflows.map((wf) => <WorkflowCard key={wf.id} wf={wf} />)
                    ) : (
                      <Card>
                        <CardContent className="py-10 text-center text-sm text-muted-foreground space-y-2">
                          <p>功能地图为空。</p>
                          {result.probe_log && result.probe_log.length > 0 && !(result.workflows && result.workflows.length) ? (
                            <p className="text-amber-700">
                              检测到有「探测展开记录」但无功能地图，说明 backend 可能是旧版本。
                              请先关闭占用 8000 端口的进程，重启 backend 后再扫描。
                            </p>
                          ) : (
                            <p>请重新扫描；若仍为空，请确认 backend 已重启到最新代码。</p>
                          )}
                        </CardContent>
                      </Card>
                    )}
                  </TabsContent>

                  <TabsContent value="layout" className="mt-4">
                    <Card>
                      <CardHeader>
                        <CardTitle className="text-base">{result.title || "发品页"}</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <LayoutPreview result={result} />
                      </CardContent>
                    </Card>
                  </TabsContent>

                  <TabsContent value="sections" className="mt-4 space-y-4">
                    {result.sections.map((section) => (
                      <Card key={section.id}>
                        <CardHeader className="pb-2">
                          <CardTitle className="text-sm">
                            {section.title}
                            <span className="ml-2 text-xs font-normal text-muted-foreground">
                              Y≈{section.y_start} · {section.elements.length} 项
                            </span>
                          </CardTitle>
                        </CardHeader>
                        <CardContent className="grid gap-2 md:grid-cols-2">
                          {section.elements.map((el) => (
                            <ElementRow key={el.id} el={el} />
                          ))}
                        </CardContent>
                      </Card>
                    ))}
                  </TabsContent>

                  <TabsContent value="all" className="mt-4">
                    <div className="grid gap-2 md:grid-cols-2">
                      {result.elements.map((el) => (
                        <ElementRow key={el.id} el={el} />
                      ))}
                    </div>
                  </TabsContent>
                </Tabs>

                {result.probe_log && result.probe_log.length > 0 ? (
                  <Card>
                    <CardHeader>
                      <CardTitle className="text-base">探测展开记录</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-2 text-sm">
                      {result.probe_log.map((p, i) => (
                        <div key={i} className="rounded border p-2">
                          点击「{p.button}」→ 新增 {p.new_elements} 个元素
                        </div>
                      ))}
                    </CardContent>
                  </Card>
                ) : null}
              </>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
