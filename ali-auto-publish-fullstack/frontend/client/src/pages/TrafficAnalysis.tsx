import { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ChevronRight, Wand2 } from "lucide-react";
import { analysisApi, configApi, ensureRuntimeSecretsForAiTask, getMembershipToken, isDesktopClient } from "@/lib/api";
import { applyRuntimeApiKey, isMaskedSecret, useAdminRuntimeConfigSync } from "@/hooks/useAdminRuntimeConfigSync";
import { toast } from "sonner";

type TrafficAiResult = {
  output_file?: string;
  content?: string;
  generated_at?: string;
};


export default function TrafficAnalysis() {
  const [apiKey, setApiKey] = useState("");
  const [apiKeyEditing, setApiKeyEditing] = useState("");
  const [isApiKeyEditing, setIsApiKeyEditing] = useState(false);
  const [modelName, setModelName] = useState("doubao-seed-2-0-pro-260215");
  const [outputFile, setOutputFile] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult] = useState<TrafficAiResult>({});
  const [pointsEstimate, setPointsEstimate] = useState<Record<string, any> | null>(null);
  const [pointsPerRun, setPointsPerRun] = useState(0.5);

  const isAdminSession = useMemo(() => {
    try {
      return (localStorage.getItem("admin_console_logged_in") || "") === "1";
    } catch {
      return false;
    }
  }, []);

  const loadConfig = async () => {
    try {
      const da = (await configApi.getSection("data_analysis")) || {};
      const rawKey = String(da.doubao_api_key || "");
      setApiKey(rawKey);
      setApiKeyEditing(rawKey);
      setIsApiKeyEditing(false);
      setModelName(da.doubao_model_name || "doubao-seed-2-0-pro-260215");
      setOutputFile(da.traffic_ai_output_file || "");
    } catch {
      // ignore
    }
  };

  const apiKeyRef = useRef(apiKey);
  apiKeyRef.current = apiKey;

  useAdminRuntimeConfigSync({
    enabled: isDesktopClient() && !!getMembershipToken(),
    skipSync: () => isApiKeyEditing,
    onDataAnalysisChange: (da) => {
      if (da.doubao_model_name) {
        setModelName(String(da.doubao_model_name));
      }
      applyRuntimeApiKey(
        da.doubao_api_key,
        apiKeyRef.current,
        setApiKey,
        setApiKeyEditing
      );
    },
  });

  const saveConfig = async () => {
    try {
      const finalKey = isApiKeyEditing ? String(apiKeyEditing || "").trim() : String(apiKey || "").trim();
      const current = (await configApi.getSection("data_analysis")) || {};
      const adminFields: Record<string, string> = {};
      if (isAdminSession) {
        if (modelName) adminFields.doubao_model_name = modelName;
        if (finalKey && !isMaskedSecret(finalKey)) {
          adminFields.doubao_api_key = finalKey;
        }
      }
      await configApi.updateSection("data_analysis", {
        ...current,
        ...adminFields,
        traffic_ai_output_file: outputFile,
      });
      configApi.invalidateCache();
      setApiKey(finalKey);
      setApiKeyEditing(finalKey);
      setIsApiKeyEditing(false);
      toast.success("流量分析配置已保存");
    } catch (e: any) {
      toast.error(e?.message || "保存配置失败");
    }
  };

  const refreshStatus = async () => {
    try {
      const res = await analysisApi.getStatus("traffic_ai");
      const payload = res?.data || res;
      const status = payload?.data || payload;
      setIsRunning(status?.status === "running" || status?.status === "stopping");
    } catch {
      // ignore
    }
  };

  const refreshResult = async () => {
    try {
      const res = await analysisApi.getTrafficAiResult();
      const payload = res?.data || res;
      const data = payload?.data || payload;
      if (data && (data.content || data.output_file || data.generated_at)) {
        setResult(data);
      }
    } catch {
      // 保留当前展示，避免轮询/二次进入页面时数据被清空
    }
  };

  const refreshPointsPricing = async () => {
    try {
      const res: any = await analysisApi.getPointsPricing();
      const payload = res?.data ?? res;
      const data = payload?.data ?? payload ?? {};
      const v = Number(data?.traffic_ai_per_run);
      if (Number.isFinite(v) && v >= 0) setPointsPerRun(v);
    } catch {
      // keep default
    }
  };

  const refreshPointsEstimate = async () => {
    if (isAdminSession) {
      setPointsEstimate({ skip_points: true });
      return;
    }
    try {
      const res: any = await analysisApi.getTrafficAiPointsEstimate();
      const payload = res?.data ?? res;
      const est = payload?.data ?? payload ?? null;
      setPointsEstimate(est);
      const per = Number(est?.per_run_cost);
      if (Number.isFinite(per) && per >= 0) setPointsPerRun(per);
    } catch {
      setPointsEstimate(null);
    }
  };

  const startAnalyze = async () => {
    try {
      if (!isAdminSession) {
        let estimate: Record<string, any> | null = null;
        try {
          const estRes: any = await analysisApi.getTrafficAiPointsEstimate();
          const estPayload = estRes?.data ?? estRes;
          estimate = estPayload?.data ?? estPayload ?? null;
          setPointsEstimate(estimate);
        } catch {
          estimate = null;
        }
        if (estimate && estimate.skip_points !== true && estimate.sufficient === false) {
          toast.error(
            `积分不足：余额 ${estimate.balance ?? 0}，预计至少需 ${estimate.estimated_total_cost ?? estimate.whole_points_required ?? 0} 积分`
          );
          return;
        }
      }

      await ensureRuntimeSecretsForAiTask();
      await analysisApi.start({ task_type: "traffic_ai" });
      toast.success("店铺整体数据分析已启动");
      refreshStatus();
      const poll = setInterval(async () => {
        try {
          await refreshResult();
          const res = await analysisApi.getStatus("traffic_ai");
          const payload = res?.data || res;
          const status = payload?.data || payload;
          const s = status?.status;
          if (s === "completed" || s === "failed" || s === "idle") {
            clearInterval(poll);
            await refreshResult();
            await refreshStatus();
          }
        } catch {
          // ignore
        }
      }, 1500);
    } catch (e: any) {
      toast.error(e?.message || "启动失败");
    }
  };

  const stopAnalyze = async () => {
    try {
      await analysisApi.stop("traffic_ai");
      toast.info("已请求停止分析");
      refreshStatus();
    } catch (e: any) {
      toast.error(e?.message || "停止失败");
    }
  };

  useEffect(() => {
    loadConfig();
    refreshResult();
    refreshPointsPricing();
    refreshPointsEstimate();
    void refreshStatus();
  }, []);

  useEffect(() => {
    if (!isRunning) return;
    const t = setInterval(refreshStatus, 4000);
    return () => clearInterval(t);
  }, [isRunning]);

  const modules = useMemo(() => {
    const txt = String(result?.content || "");
    if (!txt.trim()) return [] as Array<{ title: string; body: string }>;

    const lines = txt.split(/\r?\n/);
    const parsed: Array<{ title: string; body: string; moduleNo?: number }> = [];
    let currentTitle = "完整分析结果";
    let buffer: string[] = [];

    const pushCurrent = () => {
      const body = buffer.join("\n").trim();
      const m = String(currentTitle || "").match(/模块\s*(\d+)/);
      const moduleNo = m ? Number(m[1]) : undefined;
      if (body || currentTitle) parsed.push({ title: currentTitle, body, moduleNo });
    };

    for (const ln of lines) {
      const t = ln.trim();
      const plain = t.replace(/^#{1,6}\s*/, "");
      const isModule = /^(模块\s*\d+|[一二三四五六七八九十]+、模块\s*\d*|模块\s*[0-9]+[:：]?)/.test(plain);
      if (isModule) {
        if (buffer.length || currentTitle) pushCurrent();
        currentTitle = plain;
        buffer = [];
      } else {
        buffer.push(ln);
      }
    }
    if (buffer.length || currentTitle) pushCurrent();

    const clean = parsed.filter((m) => (m.title || m.body) && (m.body || "").trim() !== "");

    const module7 = clean.find((x) => x.moduleNo === 7);
    const module8 = clean.find((x) => x.moduleNo === 8);
    const module9 = clean.find((x) => x.moduleNo === 9);
    const module1to6 = clean.filter((x) => x.moduleNo && x.moduleNo >= 1 && x.moduleNo <= 6);

    const validationBlock = /【结果校验告警】[\s\S]*$/m.exec(txt)?.[0] || "";

    const stripValidation = (s: string) => String(s || "").replace(/\n*---\n【结果校验告警】[\s\S]*$/m, "").trim();

    const fullBodyParts: string[] = [];
    if (module9?.body) fullBodyParts.push(stripValidation(module9.body));
    const preface = clean.find((x) => x.moduleNo === undefined && x.title === "完整分析结果");
    if (preface?.body) fullBodyParts.push(stripValidation(preface.body));

    const out: Array<{ title: string; body: string }> = [];
    out.push({ title: "完整分析结果", body: fullBodyParts.join("\n\n").trim() || "-" });

    if (module7) out.push({ title: module7.title, body: module7.body || "-" });
    if (module8) out.push({ title: module8.title, body: module8.body || "-" });
    for (const m of module1to6) out.push({ title: m.title, body: m.body || "-" });

    out.push({ title: "模块9：结果校验告警", body: validationBlock || "暂无校验告警" });

    return out;
  }, [result]);

  const renderModuleBody = (body: string) => {
    const lines = String(body || "").split(/\r?\n/);
    const nodes: Array<any> = [];
    let i = 0;

    const parseRow = (line: string) =>
      line
        .split("|")
        .map((x) => x.trim())
        .filter((x) => x.length > 0);

    while (i < lines.length) {
      const raw = lines[i] || "";
      const t = raw.trim();

      if (!t) {
        i += 1;
        continue;
      }

      const h = t.replace(/^#{1,6}\s*/, "");
      if (/^(\d+\.\d+|\d+\.|（[一二三四五六七八九十]+）|[一二三四五六七八九十]+、)/.test(h) || /^【.+】$/.test(h)) {
        nodes.push(
          <h4 key={`h-${i}`} className="text-sm font-semibold mt-3 mb-2">
            {h}
          </h4>
        );
        i += 1;
        continue;
      }

      const isPipeTable = t.includes("|") && parseRow(t).length >= 3;
      if (isPipeTable) {
        const tableLines: string[] = [];
        while (i < lines.length) {
          const tt = (lines[i] || "").trim();
          if (!tt || !tt.includes("|")) break;
          tableLines.push(tt);
          i += 1;
        }

        const rows = tableLines
          .filter((ln) => !/^\|?\s*[-:]{2,}/.test(ln.replace(/\|/g, "")))
          .map(parseRow)
          .filter((r) => r.length > 0);

        if (rows.length) {
          const head = rows[0];
          const bodyRows = rows.slice(1);
          nodes.push(
            <div key={`tb-${i}`} className="my-3 overflow-auto rounded-md border border-border/60">
              <table className="min-w-full text-xs">
                <thead className="bg-muted/60">
                  <tr>
                    {head.map((c, ci) => (
                      <th key={`th-${ci}`} className="text-left px-3 py-2 font-medium whitespace-nowrap">{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {bodyRows.map((r, ri) => (
                    <tr key={`tr-${ri}`} className="border-t">
                      {head.map((_, ci) => (
                        <td key={`td-${ri}-${ci}`} className="px-3 py-2 align-top whitespace-nowrap">{r[ci] || ""}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        continue;
      }

      nodes.push(
        <p key={`p-${i}`} className="text-sm leading-7 my-1">
          {h}
        </p>
      );
      i += 1;
    }

    return <div>{nodes}</div>;
  };

  return (
    <div className="p-8 space-y-6">
      <div>
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>数据分析</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">流量分析</span>
        </div>
        <h1 className="text-2xl font-bold text-foreground">流量分析</h1>
        <p className="text-sm text-muted-foreground mt-1">店铺整体数据AI诊断（全店运营数据 + 全店渠道数据）</p>
      </div>

      <div className="grid grid-cols-12 gap-6 items-start">
        <div className="col-span-8 space-y-6">
          {modules.length === 0 ? (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">分析结果</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-[620px] rounded-lg border border-border/50 flex items-center justify-center text-xs text-muted-foreground">
                  暂无分析内容，请点击“开始分析”
                </div>
              </CardContent>
            </Card>
          ) : (
            modules.map((m, idx) => (
              <Card key={`${m.title}-${idx}`}>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">{m.title || `模块 ${idx + 1}`}</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="rounded-lg border border-border/50 bg-card p-4">
                    {renderModuleBody(m.body || "-")}
                  </div>
                </CardContent>
              </Card>
            ))
          )}
        </div>

        <div className="col-span-4">
          <Card className="sticky top-6">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">配置模块</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {isAdminSession && (
                <>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">API_KEY</Label>
                <Input
                  type="text"
                  value={isApiKeyEditing ? apiKeyEditing : apiKey}
                  onFocus={() => {
                    setIsApiKeyEditing(true);
                    setApiKeyEditing(apiKey);
                  }}
                  onChange={(e) => {
                    setIsApiKeyEditing(true);
                    setApiKeyEditing(e.target.value);
                  }}
                  onBlur={() => {
                    const final = String(apiKeyEditing || "").trim();
                    setApiKey(final);
                    setApiKeyEditing(final);
                    setIsApiKeyEditing(false);
                  }}
                  className="text-sm font-mono"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">模型名称</Label>
                <Input value={modelName} onChange={(e) => setModelName(e.target.value)} className="text-sm" />
              </div>
                </>
              )}
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">结果TXT保存路径</Label>
                <Input value={outputFile} onChange={(e) => setOutputFile(e.target.value)} className="text-sm font-mono" />
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" variant="outline" onClick={saveConfig}>保存配置</Button>
                <Button size="sm" variant="outline" onClick={refreshResult}>刷新结果</Button>
                <Button
                  size="sm"
                  variant={isRunning ? "destructive" : "default"}
                  onClick={isRunning ? stopAnalyze : startAnalyze}
                  className="gap-2"
                >
                  <Wand2 className="w-4 h-4" />
                  {isRunning ? "停止分析" : "开始分析"}
                </Button>
              </div>

              <div className="text-xs text-muted-foreground leading-6 rounded-md border border-border/60 bg-muted/30 p-3">
                数据源固定：
                <br />
                1）全店运营数据：店铺运营数据下“周期数据趋势（周汇总）”的“总结”sheet
                <br />
                2）全店渠道数据：按“流量渠道”单日数据自动聚合上周（周日-周六）
                <br />
                输出：TXT 文件（由上方“结果TXT保存路径”控制）
                <br />
                {!isAdminSession ? (
                  <>
                    每次成功完成分析扣 {pointsPerRun} 积分
                    {pointsEstimate && pointsEstimate.skip_points !== true
                      ? ` · 余额 ${pointsEstimate.balance ?? 0}`
                      : ""}
                    <br />
                  </>
                ) : null}
                最近生成：{result.generated_at || "-"}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
