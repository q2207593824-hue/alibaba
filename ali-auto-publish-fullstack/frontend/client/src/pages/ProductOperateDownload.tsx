import { useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { toast } from "sonner";
import { configApi, dataApi } from "@/lib/api";
import { ChevronRight, Download, Pause, Play } from "lucide-react";

const DISPLAY_HEADERS = [
  "产品ID",
  "产品类型",
  "产品级别",
  "近30天搜索曝光数",
  "近30天访问人数",
  "近90天支付买家数",
  "近90天[TM+询盘]人数",
  "近90天[TM+询盘]转化",
  "近 90 天退款纠纷率",
  "近 90 天订单数",
  "近 365 天评价数",
  "近 30 天商品问题率(纠纷/差评)",
  "是否星团直供商品",
  "是否具备服务能力商品",
  "是否趋势品(有流量倾斜)",
  "竞争力等级",
  "（商机优品要求）提升近90天[TM+询盘]人数到",
  "（商机优品要求）提升近90天商品的支付买家数到",
  "（商机优品要求）提升近90天[TM+询盘]转化到",
  "提升近30天访客人数到",
];

export default function ProductOperateDownload() {
  const taskType = useMemo(() => "product_operate", []);
  const [isRunning, setIsRunning] = useState(false);
  const [taskStatus, setTaskStatus] = useState<any>(null);
  const [outputFile, setOutputFile] = useState("");
  const [tableData, setTableData] = useState<{ columns: string[]; rows: any[] }>({ columns: [], rows: [] });
  const [tableError, setTableError] = useState("");
  const [tableSearch, setTableSearch] = useState("");
  const [potentialTypeFilter, setPotentialTypeFilter] = useState<"all" | "交易品" | "商机品">("all");
  const [goodToHotTypeFilter, setGoodToHotTypeFilter] = useState<"all" | "交易品" | "商机品">("all");

  const normalizePath = (input: string) => input.trim().replace(/[/]+/g, "\\");

  const loadConfig = async () => {
    try {
      const dd = (await configApi.getSection("data_download")) || {};
      setOutputFile(dd?.product_operate_output_file || "");
    } catch (e: any) {
      toast.error(e.message || "加载配置失败");
    }
  };

  const saveConfig = async () => {
    try {
      const current = (await configApi.getSection("data_download")) || {};
      await configApi.updateSection("data_download", {
        ...current,
        product_operate_output_file: normalizePath(outputFile),
      });
      toast.success("产品运营配置已保存");
    } catch (e: any) {
      toast.error(e.message || "保存失败");
    }
  };

  const refreshStatus = async () => {
    try {
      const res = await dataApi.getDownloadStatus(taskType);
      const data = res?.data || res;
      const status = data?.data || data;
      setTaskStatus(status);
      setIsRunning(status?.status === "running" || status?.status === "stopping");
    } catch {
      // ignore
    }
  };

  const refreshTable = async () => {
    try {
      const file = normalizePath(outputFile || "");
      const res = await dataApi.getProductOperateTable(file || undefined);
      const payload = res?.data || res;
      const data = payload?.data || payload || {};
      setTableData({
        columns: Array.isArray(data?.columns) ? data.columns : [],
        rows: Array.isArray(data?.rows) ? data.rows : [],
      });
      setTableError(String(data?.error || ""));
    } catch {
      setTableData({ columns: [], rows: [] });
      setTableError("读取失败：接口请求异常");
    }
  };

  const handleStart = async () => {
    try {
      if (!outputFile.trim()) {
        toast.error("请先配置输出文件路径");
        return;
      }
      setIsRunning(true);
      await saveConfig();
      await dataApi.startDownload({ task_type: taskType });
      toast.success("产品运营下载已启动");
      refreshStatus();
      setTimeout(() => refreshTable(), 1200);
    } catch (e: any) {
      toast.error(e.message || "启动失败");
      setIsRunning(false);
    }
  };

  const handleStop = async () => {
    try {
      await dataApi.stopDownload(taskType);
      toast.info("已停止");
      setIsRunning(false);
      refreshStatus();
    } catch (e: any) {
      toast.error(e.message || "停止失败");
    }
  };

  useEffect(() => {
    loadConfig();
    refreshStatus();
  }, []);

  useEffect(() => {
    if (!isRunning) return;
    const timer = setInterval(async () => {
      await refreshStatus();
    }, 2000);
    return () => clearInterval(timer);
  }, [isRunning]);

  useEffect(() => {
    if (taskStatus?.status !== "failed") return;
    const err = String(taskStatus?.error || "").trim();
    if (err) toast.error(err);
  }, [taskStatus?.status, taskStatus?.error]);

  useEffect(() => {
    refreshTable();
  }, [outputFile]);

  useEffect(() => {
    if (!isRunning) return;
    const timer = setInterval(() => {
      refreshTable();
    }, 3000);
    return () => clearInterval(timer);
  }, [isRunning, outputFile]);

  const phaseText = (() => {
    const step = String(taskStatus?.current_step || "");
    if (step.includes("潜力优品")) return "资源优先堆给需要的产品，提高优爆品占比（当前：潜力优品）";
    if (step.includes("优品")) return "资源优先堆给需要的产品，提高优爆品占比（当前：优品）";
    if (step.includes("爆品")) return "资源优先堆给需要的产品，提高优爆品占比（当前：爆品）";
    return "资源优先堆给需要的产品，提高优爆品占比";
  })();

  const toNum = (v: any): number => {
    const s = String(v ?? "").replace(/,/g, "").trim();
    if (!s) return 0;
    const n = Number(s);
    return Number.isFinite(n) ? n : 0;
  };

  const toRate = (v: any): number => {
    const s = String(v ?? "").trim();
    if (!s) return 0;
    if (s.endsWith("%")) {
      const n = Number(s.replace("%", "").trim());
      return Number.isFinite(n) ? n / 100 : 0;
    }
    const n = Number(s.replace(/,/g, ""));
    if (!Number.isFinite(n)) return 0;
    return n > 1 ? n / 100 : n;
  };

  const inferType = (raw: any): "交易品" | "商机品" | "" => {
    const s = String(raw ?? "");
    if (s.includes("交易品")) return "交易品";
    if (s.includes("商机品")) return "商机品";
    return "";
  };

  const buildGapText = (label: string, need: number, curr: number, suffix: string = "个") => {
    const gap = Math.max(0, need - curr);
    if (gap <= 0) return "";
    if (suffix === "%") return `${label}还差${(gap * 100).toFixed(2)}%`;
    return `${label}还差${Math.ceil(gap)}${suffix}`;
  };

  const potentialToGoodRows = useMemo(() => {
    const rows = Array.isArray(tableData.rows) ? tableData.rows : [];
    const result: Array<{ productId: string; productType: string; isTrend: string; unmet: string }> = [];

    for (const row of rows) {
      const level = String(row?.["产品级别"] ?? "").trim();
      if (level && level !== "潜力优品") continue;

      const productType = inferType(row?.["产品类型"]);
      if (!productType) continue;

      const uv30 = toNum(row?.["近30天访问人数"]);
      const pay90 = toNum(row?.["近90天支付买家数"]);
      const tm90 = toNum(row?.["近90天[TM+询盘]人数"]);

      const unmet: string[] = [];
      if (uv30 < 1) unmet.push(buildGapText("近30天访问人数", 1, uv30));
      if (productType === "交易品") {
        if (pay90 < 1) unmet.push(buildGapText("近90天支付买家数", 1, pay90));
      } else if (productType === "商机品") {
        if (tm90 < 2) unmet.push(buildGapText("近90天[TM+询盘]人数", 2, tm90));
      }

      const filtered = unmet.filter(Boolean);
      if (filtered.length === 1) {
        result.push({
          productId: String(row?.["产品ID"] ?? ""),
          productType,
          isTrend: String(row?.["是否趋势品(有流量倾斜)"] ?? ""),
          unmet: filtered[0],
        });
      }
    }
    return result;
  }, [tableData.rows]);

  const goodToHotRows = useMemo(() => {
    const rows = Array.isArray(tableData.rows) ? tableData.rows : [];
    const result: Array<{ productId: string; productType: string; isTrend: string; unmet: string }> = [];

    for (const row of rows) {
      const level = String(row?.["产品级别"] ?? "").trim();
      if (level && level !== "优品") continue;

      const productType = inferType(row?.["产品类型"]);
      if (!productType) continue;

      const uv30 = toNum(row?.["近30天访问人数"]);
      const pay90 = toNum(row?.["近90天支付买家数"]);
      const tm90 = toNum(row?.["近90天[TM+询盘]人数"]);
      const rate90 = toRate(row?.["近90天[TM+询盘]转化"]);

      const unmet: string[] = [];
      if (uv30 < 1) unmet.push(buildGapText("近30天访问人数", 1, uv30));
      if (productType === "交易品") {
        if (pay90 < 5) unmet.push(buildGapText("近90天支付买家数", 5, pay90));
        if (rate90 < 0.01) unmet.push(buildGapText("近90天[TM+询盘]转化", 0.01, rate90, "%"));
      } else if (productType === "商机品") {
        if (pay90 < 3) unmet.push(buildGapText("近90天支付买家数", 3, pay90));
        if (tm90 < 20) unmet.push(buildGapText("近90天[TM+询盘]人数", 20, tm90));
        if (rate90 < 0.02) unmet.push(buildGapText("近90天[TM+询盘]转化", 0.02, rate90, "%"));
      }

      const filtered = unmet.filter(Boolean);
      if (filtered.length >= 1 && filtered.length <= 2) {
        result.push({
          productId: String(row?.["产品ID"] ?? ""),
          productType,
          isTrend: String(row?.["是否趋势品(有流量倾斜)"] ?? ""),
          unmet: filtered.join("；"),
        });
      }
    }
    return result;
  }, [tableData.rows]);

  const potentialToGoodRowsFiltered = useMemo(() => {
    if (potentialTypeFilter === "all") return potentialToGoodRows;
    return potentialToGoodRows.filter((r) => r.productType === potentialTypeFilter);
  }, [potentialToGoodRows, potentialTypeFilter]);

  const goodToHotRowsFiltered = useMemo(() => {
    if (goodToHotTypeFilter === "all") return goodToHotRows;
    return goodToHotRows.filter((r) => r.productType === goodToHotTypeFilter);
  }, [goodToHotRows, goodToHotTypeFilter]);

  const mainTableRowsFiltered = useMemo(() => {
    const rows = Array.isArray(tableData.rows) ? tableData.rows : [];
    const kw = tableSearch.trim().toLowerCase();
    if (!kw) return rows;
    return rows.filter((row) => {
      const pid = String(row?.["产品ID"] ?? "").toLowerCase();
      const ptype = String(row?.["产品类型"] ?? "").toLowerCase();
      const plevel = String(row?.["产品级别"] ?? "").toLowerCase();
      return pid.includes(kw) || ptype.includes(kw) || plevel.includes(kw);
    });
  }, [tableData.rows, tableSearch]);

  return (
    <div className="p-8">
      <div className="mb-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>数据下载</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">产品运营</span>
        </div>
        <h1 className="text-2xl font-bold text-foreground">产品运营数据下载</h1>
        <p className="text-sm text-muted-foreground mt-1">优品➡优品➡爆品</p>
      </div>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2 space-y-6">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">执行控制</CardTitle>
                <div className="flex items-center gap-3">
                  <Badge variant={isRunning ? "default" : "secondary"} className="gap-1.5">
                    <span className={`w-1.5 h-1.5 rounded-full ${isRunning ? "bg-green-400 animate-pulse" : "bg-gray-400"}`} />
                    {isRunning ? "运行中" : "待启动"}
                  </Badge>
                  <Button size="sm" onClick={isRunning ? handleStop : handleStart} variant={isRunning ? "destructive" : "default"} className="gap-2">
                    {isRunning ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                    {isRunning ? "停止" : "开始下载"}
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-2">
              <div className="w-full text-center text-3xl font-extrabold tracking-wide text-foreground leading-tight">
                {phaseText}
              </div>
              <div className="text-xs text-muted-foreground">
                {taskStatus?.current_step ? `当前步骤：${taskStatus.current_step}` : "就绪"}
              </div>
              {taskStatus?.status === "failed" && taskStatus?.error ? (
                <div className="text-xs text-destructive">下载失败：{taskStatus.error}</div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">产品运营数据</CardTitle>
                <div className="flex items-center gap-2">
                  <Input
                    value={tableSearch}
                    onChange={(e) => setTableSearch(e.target.value)}
                    placeholder="搜索：产品ID/产品类型/产品级别"
                    className="h-8 w-56 text-xs"
                  />
                  <Button size="sm" variant="ghost" onClick={refreshTable}>刷新</Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="h-80 overflow-auto rounded-lg border border-border/50">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                    <tr className="border-b">
                      {(tableData.columns || []).length === 0 ? (
                        <th className="text-left py-3 px-3 font-medium text-muted-foreground">暂无列</th>
                      ) : (
                        tableData.columns.map((c) => (
                          <th key={c} className="text-left py-3 px-3 font-medium text-muted-foreground whitespace-nowrap">{c}</th>
                        ))
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {mainTableRowsFiltered.length === 0 ? (
                      <tr>
                        <td colSpan={Math.max((tableData.columns || []).length, 1)} className="py-6 text-center text-muted-foreground">
                          {tableSearch.trim() ? "无匹配结果" : (tableError || "暂无数据（请先执行下载，或检查输出文件路径）")}
                        </td>
                      </tr>
                    ) : (
                      mainTableRowsFiltered.map((row, i) => (
                        <tr key={i} className="border-b last:border-0 hover:bg-accent/30">
                          {tableData.columns.map((c) => (
                            <td key={c} className="py-2.5 px-3 whitespace-nowrap">{String(row?.[c] ?? "")}</td>
                          ))}
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-2">
                <CardTitle className="text-base">潜力优品➡优品（只差1项）</CardTitle>
                <div className="flex items-center gap-1">
                  <Button size="sm" variant={potentialTypeFilter === "all" ? "default" : "outline"} onClick={() => setPotentialTypeFilter("all")}>全部</Button>
                  <Button size="sm" variant={potentialTypeFilter === "交易品" ? "default" : "outline"} onClick={() => setPotentialTypeFilter("交易品")}>交易品</Button>
                  <Button size="sm" variant={potentialTypeFilter === "商机品" ? "default" : "outline"} onClick={() => setPotentialTypeFilter("商机品")}>商机品</Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="h-[336px] overflow-auto rounded-lg border border-border/50">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                    <tr className="border-b">
                      <th className="text-left py-3 px-3 font-medium text-muted-foreground whitespace-nowrap">产品ID</th>
                      <th className="text-left py-3 px-3 font-medium text-muted-foreground whitespace-nowrap">产品类型</th>
                      <th className="text-left py-3 px-3 font-medium text-muted-foreground whitespace-nowrap">是否趋势品(有流量倾斜)</th>
                      <th className="text-left py-3 px-3 font-medium text-muted-foreground whitespace-nowrap">未满足项</th>
                    </tr>
                  </thead>
                  <tbody>
                    {potentialToGoodRowsFiltered.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="py-6 text-center text-muted-foreground">暂无即将满足优品条件的数据</td>
                      </tr>
                    ) : (
                      potentialToGoodRowsFiltered.map((r) => (
                        <tr key={`${r.productId}-${r.unmet}`} className="border-b last:border-0 hover:bg-accent/30">
                          <td className="py-2.5 px-3 whitespace-nowrap">{r.productId}</td>
                          <td className="py-2.5 px-3 whitespace-nowrap">{r.productType}</td>
                          <td className="py-2.5 px-3 whitespace-nowrap">{r.isTrend}</td>
                          <td className="py-2.5 px-3">{r.unmet}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-2">
                <CardTitle className="text-base">优品➡爆品（只差1-2项）</CardTitle>
                <div className="flex items-center gap-1">
                  <Button size="sm" variant={goodToHotTypeFilter === "all" ? "default" : "outline"} onClick={() => setGoodToHotTypeFilter("all")}>全部</Button>
                  <Button size="sm" variant={goodToHotTypeFilter === "交易品" ? "default" : "outline"} onClick={() => setGoodToHotTypeFilter("交易品")}>交易品</Button>
                  <Button size="sm" variant={goodToHotTypeFilter === "商机品" ? "default" : "outline"} onClick={() => setGoodToHotTypeFilter("商机品")}>商机品</Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="h-[336px] overflow-auto rounded-lg border border-border/50">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                    <tr className="border-b">
                      <th className="text-left py-3 px-3 font-medium text-muted-foreground whitespace-nowrap">产品ID</th>
                      <th className="text-left py-3 px-3 font-medium text-muted-foreground whitespace-nowrap">产品类型</th>
                      <th className="text-left py-3 px-3 font-medium text-muted-foreground whitespace-nowrap">是否趋势品(有流量倾斜)</th>
                      <th className="text-left py-3 px-3 font-medium text-muted-foreground whitespace-nowrap">未满足项</th>
                    </tr>
                  </thead>
                  <tbody>
                    {goodToHotRowsFiltered.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="py-6 text-center text-muted-foreground">暂无即将满足爆品条件的数据</td>
                      </tr>
                    ) : (
                      goodToHotRowsFiltered.map((r) => (
                        <tr key={`${r.productId}-${r.unmet}`} className="border-b last:border-0 hover:bg-accent/30">
                          <td className="py-2.5 px-3 whitespace-nowrap">{r.productId}</td>
                          <td className="py-2.5 px-3 whitespace-nowrap">{r.productType}</td>
                          <td className="py-2.5 px-3 whitespace-nowrap">{r.isTrend}</td>
                          <td className="py-2.5 px-3">{r.unmet}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">配置</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">输出文件路径</Label>
                <Input
                  value={outputFile}
                  onChange={(e) => setOutputFile(e.target.value)}
                  placeholder="D:\\店铺数据\\数据下载\\产品运营\\产品运营.xlsx"
                  className="text-xs font-mono"
                />
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={saveConfig}>保存配置</Button>
                <Button size="sm" variant="ghost" onClick={loadConfig}>重载</Button>
                <Button size="sm" variant="ghost" onClick={refreshTable}>刷新数据</Button>
              </div>
              <Separator />
              <div className="text-[11px] text-muted-foreground space-y-1">
                <div className="font-semibold text-foreground">国际站规则（产品运营）</div>
                <div className="font-medium text-foreground/90">潜力优品➡优品</div>
                <div>交易品：近90天支付买家数≥1 且 近30天访问人数≥1</div>
                <div>商机品：近90天[TM+询盘]人数≥2 且 近30天访问人数≥1</div>
                <div className="pt-1 font-medium text-foreground/90">优品➡爆品</div>
                <div>交易品：近90天支付买家数≥5，近90天[TM+询盘]转化≥1%，近30天访问人数≥1</div>
                <div>商机品：近90天支付买家数≥3，近30天访问人数≥1，近90天[TM+询盘]人数≥20，近90天[TM+询盘]转化≥2%</div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">下载说明</CardTitle>
            </CardHeader>
            <CardContent className="text-[11px] text-muted-foreground leading-5">
              <div className="flex items-start gap-2">
                <Download className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <span>将自动抓取潜力优品、优品、爆品三个标签的分页数据，并实时覆盖输出文件。</span>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
