/**
 * StoreDataDownload - 店铺运营数据下载页面
 * 对应脚本: cs_数据概览下载_正式发布.py
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ChevronRight, Eye, MousePointer, MessageSquare, Target, Play, Pause } from "lucide-react";
import { toast } from "sonner";
import { configApi, createLogSocket, dataApi } from "@/lib/api";

export default function StoreDataDownload() {
  const [isRunning, setIsRunning] = useState(false);
  const [periodType, setPeriodType] = useState<"day" | "week" | "month">("week");
  const [logs, setLogs] = useState<string[]>(["[系统] 店铺数据下载模块已就绪"]);

  const [savePath, setSavePath] = useState("");
  const [summaryOutputPath, setSummaryOutputPath] = useState("");
  const [storeData, setStoreData] = useState<any>({ indicators: [], periods: [] });
  const [summaryTable, setSummaryTable] = useState<any>({ sheet: "", sheets: [], columns: [], rows: [] });
  const [summarySheet, setSummarySheet] = useState("总结");
  const [currentUrlHint, setCurrentUrlHint] = useState("");
  const [isLoadingData, setIsLoadingData] = useState(false);
  const lastStatusLogRef = useRef("");

  const taskType = "store_overview";

  const loadConfig = async () => {
    try {
      const cfg = (await configApi.getSection("store_overview")) || {};
      setSavePath(cfg.save_path || "");
      setSummaryOutputPath(cfg.summary_output_path || "");
      setPeriodType((cfg.period_type || "week") as "day" | "week" | "month");
    } catch (e: any) {
      toast.error(e.message || "加载配置失败");
    }
  };

  const saveConfig = async () => {
    try {
      const current = (await configApi.getSection("store_overview")) || {};
      await configApi.updateSection("store_overview", {
        ...current,
        // 固定为数据概览首页，避免因历史配置导致抓取页错误
        data_url: "https://data.alibaba.com/?spm=a2793.11769229.0.0.20023e5fc1895x",
        save_path: savePath,
        summary_output_path: summaryOutputPath,
        period_type: periodType,
      });
      toast.success("店铺运营配置已保存");
      refreshStoreData();
    } catch (e: any) {
      toast.error(e.message || "保存失败");
    }
  };

  const refreshStatus = async () => {
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
    } catch {
      // ignore
    }
  };

  const refreshStoreData = async () => {
    try {
      setIsLoadingData(true);
      const [overviewRes, summaryRes] = await Promise.all([
        dataApi.getStoreOverviewLatest(savePath),
        dataApi.getStoreSummaryTable(summaryOutputPath, summarySheet || undefined),
      ]);

      const overviewPayload = overviewRes?.data ?? overviewRes;
      const overviewData = overviewPayload?.data ?? overviewPayload ?? { indicators: [], periods: [] };
      setStoreData(overviewData);
      setCurrentUrlHint(String(overviewPayload?.current_url || overviewPayload?.url || overviewData?.current_url || overviewData?.url || ""));

      const summaryPayload = summaryRes?.data ?? summaryRes;
      const summary = summaryPayload?.data ?? summaryPayload ?? { sheet: "", sheets: [], columns: [], rows: [] };
      setSummaryTable(summary);
      if (!summarySheet && summary?.sheet) setSummarySheet(summary.sheet);
    } catch {
      // ignore
    } finally {
      setIsLoadingData(false);
    }
  };

  const handleStart = async () => {
    try {
      if (!savePath) {
        toast.error("请先配置Excel保存路径");
        return;
      }
      setIsRunning(true);
      setLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] 开始店铺运营数据下载...`]);
      await dataApi.startDownload({ task_type: "store_overview" });
      toast.success("店铺日/周/月数据下载已启动");
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

  useEffect(() => {
    loadConfig();
  }, []);

  useEffect(() => {
    if (!savePath) return;

    // 首屏先拉摘要（更快）
    (async () => {
      try {
        setIsLoadingData(true);
        const [overviewRes, summaryRes] = await Promise.all([
          dataApi.getStoreOverviewLatest(savePath, false),
          dataApi.getStoreSummaryTable(summaryOutputPath, summarySheet || "总结"),
        ]);

        const overviewPayload = overviewRes?.data ?? overviewRes;
        const overviewData = overviewPayload?.data ?? overviewPayload ?? { indicators: [], periods: [] };
        setStoreData(overviewData);
        setCurrentUrlHint(String(overviewPayload?.current_url || overviewPayload?.url || overviewData?.current_url || overviewData?.url || ""));

        const summaryPayload = summaryRes?.data ?? summaryRes;
        const summary = summaryPayload?.data ?? summaryPayload ?? { sheet: "", sheets: [], columns: [], rows: [] };
        setSummaryTable(summary);
      } catch {
        // ignore
      } finally {
        setIsLoadingData(false);
      }

      // 再异步补全明细表格
      setTimeout(() => {
        refreshStoreData();
      }, 0);
    })();
  }, [savePath, summaryOutputPath, summarySheet]);

  useEffect(() => {
    void refreshStatus();
  }, []);

  useEffect(() => {
    if (!isRunning) return;
    const timer = setInterval(refreshStatus, 3000);
    return () => clearInterval(timer);
  }, [isRunning]);

  useEffect(() => {
    const ws = createLogSocket((data) => {
      if (!data) return;
      const payload = data.data || data;
      const moduleName = String(payload?.module || "");
      const msg = payload.message || payload.msg || payload.text;
      if (!msg) return;
      if (moduleName && moduleName !== "data_download") return;
      const text = String(msg);
      if (!text.includes("店铺") && !text.includes("概览")) return;
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

  const indicators = storeData?.indicators || [];

  const summary = useMemo(() => {
    const map = Object.fromEntries(indicators.map((i: any) => [i.name, i.current || 0]));
    return {
      exposure: map["全店曝光次数"] || 0,
      clicks: map["全店点击次数"] || 0,
      opportunities: map["全店品的商机量"] || 0,
      naturalOpportunities: map["自然商机量"] || 0,
    };
  }, [indicators]);

  const shopDiagnosis = useMemo(() => {
    const cols: string[] = Array.isArray(summaryTable?.columns) ? summaryTable.columns : [];
    const rows: any[] = Array.isArray(summaryTable?.rows) ? summaryTable.rows : [];
    if (!cols.length || !rows.length) {
      return {
        ready: false,
        status: "暂无诊断数据",
        core: "请先选择“总结”sheet并刷新周汇总数据",
        reason: "",
        factors: [] as Array<{ name: string; ratio: number; level: string; dir: "up" | "down" | "flat" }>,
      };
    }

    const metricCol = cols[0] || "指标名称";
    const momCol = cols.find((c) => String(c).includes("我的环比")) || "我的环比";

    const parseRatio = (v: any) => {
      if (v == null || v === "") return 0;
      const s = String(v).trim();
      if (s.includes("%")) {
        const n = Number(s.replace(/%/g, "").replace(/,/g, ""));
        return Number.isFinite(n) ? n / 100 : 0;
      }
      const n = Number(s.replace(/,/g, ""));
      if (!Number.isFinite(n)) return 0;
      return Math.abs(n) > 1 ? n / 100 : n;
    };

    const pickRatio = (candidates: string[]) => {
      const hit = rows.find((r) => {
        const name = String(r?.[metricCol] ?? "").trim();
        return candidates.some((k) => name === k || name.includes(k));
      });
      return parseRatio(hit?.[momCol]);
    };

    const factors = [
      { name: "全店曝光次数", ratio: pickRatio(["全店曝光次数", "全店曝光"]) },
      { name: "全店点击次数", ratio: pickRatio(["全店点击次数", "全店点击"]) },
      { name: "店铺访问人数", ratio: pickRatio(["店铺访问人数", "访问人数"]) },
      { name: "商机人数", ratio: pickRatio(["商机人数", "全店品的商机量", "商机量", "全店商机量"]) },
    ].map((f) => {
      const r = f.ratio;
      const abs = Math.abs(r);
      let level = "正常波动";
      let dir: "up" | "down" | "flat" = "flat";
      if (r > 0.05 && r <= 0.1) {
        level = "小幅涨";
        dir = "up";
      } else if (r > 0.1 && r <= 0.2) {
        level = "明显涨";
        dir = "up";
      } else if (r > 0.2) {
        level = "大幅涨/爆发";
        dir = "up";
      } else if (r < -0.05 && r >= -0.1) {
        level = "小幅跌";
        dir = "down";
      } else if (r < -0.1 && r >= -0.2) {
        level = "明显跌";
        dir = "down";
      } else if (r < -0.2) {
        level = "大幅跌/崩盘";
        dir = "down";
      } else if (abs <= 0.05) {
        level = "正常波动";
        dir = "flat";
      }
      return { ...f, level, dir };
    });

    const dir = (name: string) => factors.find((f) => f.name === name)?.dir || "flat";
    const exp = dir("全店曝光次数");
    const clk = dir("全店点击次数");
    const vis = dir("店铺访问人数");
    const opp = dir("商机人数");

    let core = "结构平稳，建议持续观察";
    let reason = "各指标在正常波动区间内，整体运营节奏稳定";
    let status = "稳定运行";

    if (exp === "up" && clk === "up" && vis === "up" && opp === "up") {
      core = "点击链路稳定，访客与商机同步增长";
      reason = "流量质量提升，主图与详情承接良好，关键词匹配度较高";
      status = "全面健康增长";
    } else if (exp === "up" && clk === "up" && vis === "down" && opp === "down") {
      core = "前端流量在涨，但后链路转化走弱";
      reason = "流量可能变杂，详情页说服力下降，询盘承接不足";
      status = "虚假繁荣，转化失效";
    } else if (exp === "up" && clk === "down" && vis === "up" && opp === "up") {
      core = "点击效率下降，但访客与商机仍保持增长";
      reason = "部分入口点击率下滑，老客回访或高意向访客支撑转化";
      status = "流量结构偏健康";
    } else if (exp === "up" && clk === "down" && vis === "down" && opp === "down") {
      core = "曝光增加但点击与后链路整体转弱";
      reason = "主图吸引力不足或词包偏差，导致点击率与转化同步下滑";
      status = "流量质量恶化";
    } else if (exp === "down" && clk === "up" && vis === "up" && opp === "up") {
      core = "曝光收缩但点击质量显著提升";
      reason = "流量更精准，核心关键词排名改善，页面承接较好";
      status = "精准高效，优质运营";
    } else if (exp === "down" && clk === "down" && vis === "up" && opp === "up") {
      core = "前端流量下滑，但访客与商机仍增长";
      reason = "自然/老客回流增强，或优质场景流量占比提升";
      status = "流量结构优化";
    } else if (exp === "down" && clk === "down" && vis === "down" && opp === "down") {
      core = "全链路指标同步下滑";
      reason = "店铺权重回落、预算收缩或行业淡季，需快速排查";
      status = "全面衰退，急需优化";
    }

    return { ready: true, status, core, reason, factors };
  }, [summaryTable]);

  return (
    <div className="p-8">
      <div className="mb-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>数据下载</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">店铺运营数据</span>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">店铺运营数据</h1>
            <p className="text-sm text-muted-foreground mt-1">一次下载日/周/月全部数据：运营数据.xlsx（日）、运营数据_周.xlsx、运营数据_月.xlsx</p>
            {currentUrlHint && <p className="text-xs text-muted-foreground mt-1 break-all">当前落点：{currentUrlHint}</p>}
            {isLoadingData && <p className="text-xs text-muted-foreground mt-1">正在加载数据...</p>}
          </div>
          <div className="flex items-center gap-3">
            <div className="text-xs text-muted-foreground hidden sm:block">
              下载含日/周/月三个文件
            </div>
            <Button onClick={isRunning ? handleStop : handleStart} variant={isRunning ? "destructive" : "default"} className="gap-2">
              {isRunning ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
              {isRunning ? "停止" : "开始下载"}
            </Button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4 mb-6">
        <Card><CardContent className="py-4"><div className="flex items-center gap-3"><div className="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center"><Eye className="w-5 h-5 text-blue-600" /></div><div><div className="text-xs text-muted-foreground">全店曝光</div><div className="text-lg font-bold">{Math.round(summary.exposure).toLocaleString()}</div></div></div></CardContent></Card>
        <Card><CardContent className="py-4"><div className="flex items-center gap-3"><div className="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center"><MousePointer className="w-5 h-5 text-emerald-600" /></div><div><div className="text-xs text-muted-foreground">全店点击</div><div className="text-lg font-bold">{Math.round(summary.clicks).toLocaleString()}</div></div></div></CardContent></Card>
        <Card><CardContent className="py-4"><div className="flex items-center gap-3"><div className="w-10 h-10 rounded-xl bg-amber-50 flex items-center justify-center"><MessageSquare className="w-5 h-5 text-amber-600" /></div><div><div className="text-xs text-muted-foreground">商机量</div><div className="text-lg font-bold">{Math.round(summary.opportunities).toLocaleString()}</div></div></div></CardContent></Card>
        <Card><CardContent className="py-4"><div className="flex items-center gap-3"><div className="w-10 h-10 rounded-xl bg-violet-50 flex items-center justify-center"><Target className="w-5 h-5 text-violet-600" /></div><div><div className="text-xs text-muted-foreground">自然商机</div><div className="text-lg font-bold">{Math.round(summary.naturalOpportunities).toLocaleString()}</div></div></div></CardContent></Card>
      </div>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2 space-y-6">
          <Card>
            <CardHeader className="pb-3"><CardTitle className="text-base">运营指标对比</CardTitle></CardHeader>
            <CardContent>
              {indicators.length === 0 ? (
                <div className="h-80 rounded-lg border border-border/50 flex items-center justify-center text-xs text-muted-foreground">暂无指标数据</div>
              ) : (
                <div className="grid grid-cols-2 gap-4">
                  {[indicators.slice(0, Math.ceil(indicators.length / 2)), indicators.slice(Math.ceil(indicators.length / 2))].map((col, colIdx) => (
                    <div key={colIdx} className="h-80 overflow-y-auto rounded-lg border border-border/50">
                      <table className="w-full text-sm">
                        <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                          <tr className="border-b">
                            <th className="text-left py-3 px-3 font-medium text-xs text-muted-foreground">指标名称</th>
                            <th className="text-right py-3 px-3 font-medium text-xs text-muted-foreground">当前</th>
                            <th className="text-right py-3 px-3 font-medium text-xs text-muted-foreground">行业</th>
                            <th className="text-right py-3 px-3 font-medium text-xs text-muted-foreground">优秀</th>
                          </tr>
                        </thead>
                        <tbody>
                          {col.map((ind: any) => (
                            <tr key={ind.name} className="border-b last:border-0 hover:bg-accent/30 transition-colors">
                              <td className="py-2.5 px-3">
                                <div className="flex items-center gap-2">
                                  <span className="text-xs font-medium">{ind.name}</span>
                                  <Badge variant="outline" className="text-[9px] h-4">{ind.category}</Badge>
                                </div>
                              </td>
                              <td className="py-2.5 px-3 text-right text-xs font-semibold">{Math.round(ind.current || 0).toLocaleString()}</td>
                              <td className="py-2.5 px-3 text-right text-xs text-muted-foreground">{Math.round(ind.industryAvg || 0).toLocaleString()}</td>
                              <td className="py-2.5 px-3 text-right text-xs text-muted-foreground">{Math.round(ind.peerExcellent || 0).toLocaleString()}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-2">
                <CardTitle className="text-base">周期数据趋势（周汇总）</CardTitle>
                <select className="h-8 rounded border border-input bg-background px-2 text-xs" value={summarySheet} onChange={(e) => setSummarySheet(e.target.value)}>
                  {(summaryTable.sheets || []).map((s: string) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>
            </CardHeader>
            <CardContent>
              <div className="h-[460px] overflow-auto rounded-lg border border-border/50">
                <table className="w-full text-sm min-w-[980px]">
                  {summarySheet === "总结" ? (
                    <thead>
                      <tr className="border-b bg-muted/90 sticky top-0 z-30">
                        <th className="py-2 px-4 font-medium text-xs text-left text-muted-foreground border border-border" rowSpan={2}>指标名称</th>
                        <th className="py-2 px-4 font-medium text-xs text-center text-muted-foreground border-y border-l border-border" colSpan={4}>我的数据</th>
                        <th className="py-2 px-4 font-medium text-xs text-center text-muted-foreground border-y border-l border-border" colSpan={4}>行业平均</th>
                        <th className="py-2 px-4 font-medium text-xs text-center text-muted-foreground border-y border-l border-r border-border" colSpan={4}>同行优秀</th>
                      </tr>
                      <tr className="border-b bg-muted/80 sticky top-[36px] z-20">
                        {(summaryTable.columns || []).slice(1).map((c: string, idx: number) => {
                          const colIdx = idx + 2; // 实际列序号从B开始
                          const isGroupStart = colIdx === 2 || colIdx === 6 || colIdx === 10;
                          const isGroupEnd = colIdx === 5 || colIdx === 9 || colIdx === 13;
                          return (
                            <th
                              key={c}
                              className={`py-2 px-4 font-medium text-xs text-right text-muted-foreground whitespace-nowrap border-b border-border ${isGroupStart ? "border-l" : ""} ${isGroupEnd ? "border-r" : ""}`}
                            >
                              {c}
                            </th>
                          );
                        })}
                      </tr>
                    </thead>
                  ) : (
                    <thead className="sticky top-0 bg-muted/80 backdrop-blur z-20">
                      <tr className="border-b">
                        {(summaryTable.columns || []).length === 0 ? (
                          <th className="text-left py-3 px-4 font-medium text-xs text-muted-foreground">暂无列</th>
                        ) : (summaryTable.columns || []).map((c: string, idx: number) => (
                          <th key={c} className={`py-3 px-4 font-medium text-xs text-muted-foreground ${idx === 0 ? "text-left" : "text-right"}`}>{c}</th>
                        ))}
                      </tr>
                    </thead>
                  )}
                  <tbody>
                    {(summaryTable.rows || []).length === 0 ? (
                      <tr><td colSpan={Math.max((summaryTable.columns || []).length, 1)} className="py-6 text-center text-xs text-muted-foreground">暂无周汇总数据</td></tr>
                    ) : (summaryTable.rows || []).map((row: any, i: number) => (
                      <tr key={i} className="border-b last:border-0 hover:bg-accent/30">
                        {(summaryTable.columns || []).map((c: string, idx: number) => {
                          const raw = row?.[c];
                          const isNum = typeof raw === "number";
                          const text = isNum ? Number(raw).toLocaleString() : String(raw ?? "");

                          if (idx === 0) {
                            return <td key={c} className="py-3 px-4 text-xs whitespace-nowrap text-left font-medium border-r border-border">{text}</td>;
                          }

                          const colIdx = idx + 1; // A=1 ...
                          const isGroupStart = colIdx === 2 || colIdx === 6 || colIdx === 10;
                          const isGroupEnd = colIdx === 5 || colIdx === 9 || colIdx === 13;

                          return (
                            <td key={c} className={`py-3 px-4 text-xs whitespace-nowrap text-right ${isGroupStart ? "border-l" : ""} ${isGroupEnd ? "border-r" : ""} border-border`}>
                              {text}
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
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3"><CardTitle className="text-sm">抓取配置</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Excel保存路径</Label>
                <Input value={savePath} onChange={(e) => setSavePath(e.target.value)} placeholder="运营数据.xlsx" className="text-xs font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">周汇总输出路径</Label>
                <Input value={summaryOutputPath} onChange={(e) => setSummaryOutputPath(e.target.value)} placeholder="运营数据_周汇总.xlsx" className="text-xs font-mono" />
              </div>
              <Separator />
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={saveConfig}>保存配置</Button>
                <Button size="sm" variant="ghost" onClick={loadConfig}>重载</Button>
                <Button size="sm" variant="ghost" onClick={refreshStoreData}>刷新数据</Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3"><CardTitle className="text-sm">运行日志</CardTitle></CardHeader>
            <CardContent>
              <div className="h-48 overflow-y-auto rounded-lg bg-gray-950 p-4">
                <div className="space-y-1 font-mono text-xs">
                  {logs.map((log, i) => (
                    <div key={i} className="text-gray-300">{log}</div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3"><CardTitle className="text-sm">店铺诊断结果</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="rounded-lg border border-border/60 p-3">
                <div className="text-xs text-muted-foreground">店铺状态</div>
                <div className="mt-1 text-sm font-semibold">{shopDiagnosis.status}</div>
              </div>
              <div className="rounded-lg border border-border/60 p-3">
                <div className="text-xs text-muted-foreground">核心逻辑</div>
                <div className="mt-1 text-xs leading-5">{shopDiagnosis.core}</div>
              </div>
              <div className="rounded-lg border border-border/60 p-3">
                <div className="text-xs text-muted-foreground">可能原因</div>
                <div className="mt-1 text-xs leading-5">{shopDiagnosis.reason}</div>
              </div>
              <div className="rounded-lg border border-border/60 p-3">
                <div className="text-xs text-muted-foreground mb-2">因子判定（取“我的环比”）</div>
                <div className="space-y-1">
                  {shopDiagnosis.factors.map((f) => (
                    <div key={f.name} className="flex items-center justify-between text-xs">
                      <span>{f.name}</span>
                      <span className="text-muted-foreground">{(f.ratio * 100).toFixed(2)}%</span>
                      <Badge
                        variant="outline"
                        className={f.dir === "up" ? "text-emerald-700 border-emerald-200" : f.dir === "down" ? "text-red-700 border-red-200" : "text-slate-700 border-slate-200"}
                      >
                        {f.level}
                      </Badge>
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
