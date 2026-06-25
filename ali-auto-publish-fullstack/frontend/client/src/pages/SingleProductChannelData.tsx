/**
 * 单品渠道数据 — 读取产品参谋「Excel结果」中「产品详细信息」sheet，
 * 将「各流量渠道UV分布」拆解为按渠道分列的表格。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ChevronRight, RefreshCw, Share2 } from "lucide-react";
import { analysisApi, configApi, dataApi } from "@/lib/api";
import { toast } from "sonner";

const SHEET_NAME = "产品详细信息";
const COL_PID = "产品ID";
const COL_UV = "各流量渠道UV分布";
/** 默认排序：该渠道列降序（数据中无此列时不排序） */
const DEFAULT_SORT_CHANNEL = "搜索";

function normalizePath(input: string) {
  return input.trim().replace(/[/]+/g, "\\");
}

function channelColorClass(channel: string) {
  const palettes = [
    "bg-gradient-to-br from-blue-50 to-blue-100/70 border-blue-200/70",
    "bg-gradient-to-br from-emerald-50 to-emerald-100/70 border-emerald-200/70",
    "bg-gradient-to-br from-amber-50 to-amber-100/70 border-amber-200/70",
    "bg-gradient-to-br from-purple-50 to-purple-100/70 border-purple-200/70",
    "bg-gradient-to-br from-rose-50 to-rose-100/70 border-rose-200/70",
    "bg-gradient-to-br from-cyan-50 to-cyan-100/70 border-cyan-200/70",
    "bg-gradient-to-br from-lime-50 to-lime-100/70 border-lime-200/70",
    "bg-gradient-to-br from-indigo-50 to-indigo-100/70 border-indigo-200/70",
    "bg-gradient-to-br from-orange-50 to-orange-100/70 border-orange-200/70",
    "bg-gradient-to-br from-teal-50 to-teal-100/70 border-teal-200/70",
  ];
  const s = String(channel || "");
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return palettes[h % palettes.length];
}

function channelTableAccentClass(channel: string) {
  const palettes = [
    "bg-blue-50/60",
    "bg-emerald-50/60",
    "bg-amber-50/60",
    "bg-purple-50/60",
    "bg-rose-50/60",
    "bg-cyan-50/60",
    "bg-lime-50/60",
    "bg-indigo-50/60",
    "bg-orange-50/60",
    "bg-teal-50/60",
  ];
  const s = String(channel || "");
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return palettes[h % palettes.length];
}

function normalizePid(v: unknown) {
  return String(v ?? "").replace(/\.0+$/, "").trim();
}

/** 解析 "系统推荐:100;搜索:66" 或全角分隔符 */
function parseUvDistribution(raw: unknown): Record<string, number> {
  const s = String(raw ?? "").trim();
  if (!s) return {};
  const out: Record<string, number> = {};
  const parts = s.split(/[;；]/);
  for (const part of parts) {
    const p = part.trim();
    if (!p) continue;
    const c1 = p.indexOf(":");
    const c2 = p.indexOf("：");
    const sep = c1 >= 0 && c2 >= 0 ? Math.min(c1, c2) : Math.max(c1, c2);
    if (sep < 0) continue;
    const key = p.slice(0, sep).trim();
    const valStr = p.slice(sep + 1).trim().replace(/,/g, "");
    if (!key) continue;
    const num = Number(valStr);
    out[key] = Number.isFinite(num) ? num : 0;
  }
  return out;
}

/** 按行扫描顺序收集渠道名，保证新渠道自动追加列 */
function collectChannelOrder(rows: Record<string, unknown>[]): string[] {
  const order: string[] = [];
  const seen = new Set<string>();
  for (const row of rows) {
    const parsed = parseUvDistribution(row[COL_UV]);
    for (const k of Object.keys(parsed)) {
      if (!seen.has(k)) {
        seen.add(k);
        order.push(k);
      }
    }
  }
  return order;
}

export default function SingleProductChannelData() {
  const [excelResultDir, setExcelResultDir] = useState("");
  const [p4pOutputFile, setP4pOutputFile] = useState("");
  const [loading, setLoading] = useState(false);
  const [sourceFile, setSourceFile] = useState("");
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [channelOrder, setChannelOrder] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [activeChannel, setActiveChannel] = useState<string>("");
  const [selectedProductId, setSelectedProductId] = useState("");
  const [p4pLoading, setP4pLoading] = useState(false);
  const [p4pRecentCols, setP4pRecentCols] = useState<string[]>([]);
  const [p4pRecentValues, setP4pRecentValues] = useState<Record<string, unknown>>({});
  const [p4pSheetName, setP4pSheetName] = useState("");
  const [sortKey, setSortKey] = useState<string>(DEFAULT_SORT_CHANNEL);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const loadConfig = async () => {
    try {
      const sections = await configApi.getSections(["data_download", "data_analysis"]);
      const dd = sections.data_download || {};
      const da = sections.data_analysis || {};
      const dir = dd?.product360_excel_result_dir || "";
      setExcelResultDir(dir);
      setP4pOutputFile(da?.p4p_output_file || "");
    } catch (e: any) {
      toast.error(e?.message || "加载配置失败");
    }
  };

  const refresh = useCallback(async () => {
    const dir = normalizePath(excelResultDir || "");
    if (!dir) {
      toast.error("请先在「数据下载 / 产品参谋数据」中配置 Excel 结果路径");
      setRows([]);
      setChannelOrder([]);
      setSourceFile("");
      setSortKey("");
      return;
    }
    setLoading(true);
    try {
      const res = await dataApi.getProduct360Table(dir, SHEET_NAME);
      const payload = res?.data ?? res;
      const data = payload?.data ?? payload;
      const rawRows = Array.isArray(data?.rows) ? data.rows : [];
      setSourceFile(String(data?.file || ""));
      if (!rawRows.length) {
        setRows([]);
        setChannelOrder([]);
        setSortKey("");
        return;
      }
      const hasUv = rawRows.some((r: Record<string, unknown>) => COL_UV in (r || {}));
      if (!hasUv) {
        toast.warning(`当前 sheet 中未找到「${COL_UV}」列`);
        setRows([]);
        setChannelOrder([]);
        setSortKey("");
        return;
      }
      const ch = collectChannelOrder(rawRows as Record<string, unknown>[]);
      setChannelOrder(ch);
      setRows(rawRows as Record<string, unknown>[]);
      if (ch.includes(DEFAULT_SORT_CHANNEL)) {
        setSortKey(DEFAULT_SORT_CHANNEL);
        setSortDir("desc");
      } else {
        setSortKey("");
      }
    } catch (e: any) {
      toast.error(e?.message || "加载表格失败");
      setRows([]);
      setChannelOrder([]);
      setSourceFile("");
      setSortKey("");
    } finally {
      setLoading(false);
    }
  }, [excelResultDir]);

  useEffect(() => {
    loadConfig();
  }, []);

  useEffect(() => {
    if (excelResultDir) refresh();
  }, [excelResultDir, refresh]);

  useEffect(() => {
    if (sortKey === COL_PID) setSortKey("");
  }, [sortKey]);

  useEffect(() => {
    const run = async () => {
      if (!selectedProductId || !p4pOutputFile) {
        setP4pRecentCols([]);
        setP4pRecentValues({});
        setP4pSheetName("");
        return;
      }
      setP4pLoading(true);
      try {
        // 固定读取「曝光量」sheet
        const res = await analysisApi.getP4pTable(p4pOutputFile || undefined, "曝光量");
        const payload = res?.data || res;
        const data = payload?.data || payload;
        const cols: string[] = Array.isArray(data?.columns) ? data.columns : [];
        const list: any[] = Array.isArray(data?.rows) ? data.rows : [];
        const row = list.find((r: any) => normalizePid(r?.[COL_PID]) === normalizePid(selectedProductId));
        const weekCols = cols
          .filter((c) => /^\d{6}-\d{6}$/.test(String(c)))
          .sort((a, b) => String(b).localeCompare(String(a))); // 最新 -> 最旧
        const displayCols = (weekCols.length ? weekCols : cols.filter((c) => c !== COL_PID)).slice(0, 4);
        setP4pSheetName(String(data?.sheet || "曝光量"));
        setP4pRecentCols(displayCols);
        if (!row) {
          setP4pRecentValues({});
          return;
        }
        const next: Record<string, unknown> = {};
        displayCols.forEach((c) => {
          next[c] = row?.[c] ?? "";
        });
        setP4pRecentValues(next);
      } catch {
        setP4pRecentCols([]);
        setP4pRecentValues({});
        setP4pSheetName("");
      } finally {
        setP4pLoading(false);
      }
    };
    run();
  }, [selectedProductId, p4pOutputFile]);

  const columns = useMemo(() => [COL_PID, ...channelOrder], [channelOrder]);

  const flatRows = useMemo(() => {
    return rows.map((row) => {
      const pid = row[COL_PID];
      const parsed = parseUvDistribution(row[COL_UV]);
      const rec: Record<string, string | number> = {
        [COL_PID]: pid === undefined || pid === null ? "" : String(pid),
      };
      for (const ch of channelOrder) {
        rec[ch] = Object.prototype.hasOwnProperty.call(parsed, ch) ? parsed[ch] : "";
      }
      return rec;
    });
  }, [rows, channelOrder]);

  const queryFilteredRows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return flatRows.filter((r) => {
      if (!q) return true;
      return String(r[COL_PID] ?? "").toLowerCase().includes(q);
    });
  }, [flatRows, query]);

  const maxChannelsOfRow = useCallback(
    (r: Record<string, any>) => {
      const nums = channelOrder.map((ch) => {
        const n = Number(String(r[ch] ?? "").replace(/,/g, ""));
        return Number.isFinite(n) ? n : 0;
      });
      return nums.length ? Math.max(...nums) : 0;
    },
    [channelOrder]
  );

  const isChannelTopForRow = useCallback(
    (r: Record<string, any>, ch: string) => {
      if (!ch) return true;
      const rowMax = maxChannelsOfRow(r);
      if (rowMax <= 0) return false;
      const vRaw = Number(String(r[ch] ?? "").replace(/,/g, ""));
      const v = Number.isFinite(vRaw) ? vRaw : 0;
      return v === rowMax;
    },
    [maxChannelsOfRow]
  );

  const tableRows = useMemo(() => {
    const filtered = activeChannel
      ? queryFilteredRows.filter((r) => isChannelTopForRow(r as any, activeChannel))
      : queryFilteredRows;

    if (!sortKey || sortKey === COL_PID || !columns.includes(sortKey)) return filtered;

    const sorted = [...filtered].sort((a, b) => {
      const avRaw = a[sortKey];
      const bvRaw = b[sortKey];
      const avNum = Number(String(avRaw ?? "").replace(/,/g, ""));
      const bvNum = Number(String(bvRaw ?? "").replace(/,/g, ""));
      const left = Number.isFinite(avNum) ? avNum : 0;
      const right = Number.isFinite(bvNum) ? bvNum : 0;
      return sortDir === "asc" ? left - right : right - left;
    });
    return sorted;
  }, [activeChannel, queryFilteredRows, sortKey, sortDir, columns, isChannelTopForRow]);

  const channelStats = useMemo(() => {
    const sums: Record<string, number> = {};
    for (const ch of channelOrder) sums[ch] = 0;

    // 基于“产品ID筛选”结果统计（不受卡片筛选影响，避免点卡片后卡片数值跳来跳去）
    for (const r of queryFilteredRows) {
      for (const ch of channelOrder) {
        const n = Number(String((r as any)?.[ch] ?? "").replace(/,/g, ""));
        if (Number.isFinite(n)) sums[ch] += n;
      }
    }

    const total = channelOrder.reduce((acc, ch) => acc + (sums[ch] || 0), 0);
    const items = channelOrder.map((ch) => {
      const sum = sums[ch] || 0;
      const pct = total > 0 ? (sum / total) * 100 : 0;
      return { channel: ch, sum, pct };
    });

    // 默认按占比/总量从大到小展示（更直观）
    items.sort((a, b) => b.sum - a.sum);
    return { total, items };
  }, [channelOrder, queryFilteredRows]);

  const onSortColumn = (c: string) => {
    if (c === COL_PID) return;
    if (sortKey === c) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(c);
      setSortDir("desc");
    }
  };

  const sortMark = (c: string) =>
    c === COL_PID || sortKey !== c ? "" : sortDir === "asc" ? " ↑" : " ↓";

  const activeColBg = activeChannel ? channelTableAccentClass(activeChannel) : "";

  return (
    <div className="p-8 space-y-6">
      <div>
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>数据分析</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">单品渠道数据</span>
        </div>
        <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
          <Share2 className="w-7 h-7 text-primary" />
          单品渠道数据
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          数据来源：产品参谋配置中的 Excel 结果目录 → 产品数据总报告.xlsx →「{SHEET_NAME}」sheet →「{COL_UV}」列拆解
        </p>
      </div>

      <div className="grid grid-cols-12 gap-6 items-start">
        <div className="col-span-12 lg:col-span-8">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1 space-y-1">
                  <CardTitle className="text-base">渠道 UV 透视</CardTitle>
                  <p className="text-xs text-red-600 leading-relaxed">
                    此页数据均为下载日近30天的数据-----注意：若“其他”渠道的流量占比过高，需要对直通车，关键词进行优化
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <Input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="按产品ID筛选"
                    className="h-8 w-48 text-xs"
                  />
                  <Button size="sm" variant="outline" className="gap-1.5" onClick={() => refresh()} disabled={loading}>
                    <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
                    刷新
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="mb-4">
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
                  {channelStats.items.map((it) => (
                    <div
                      key={it.channel}
                      onClick={() =>
                        setActiveChannel((prev) => (prev === it.channel ? "" : it.channel))
                      }
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setActiveChannel((prev) => (prev === it.channel ? "" : it.channel));
                        }
                      }}
                      className={`rounded-xl border px-4 py-3 shadow-sm cursor-pointer select-none hover:brightness-[0.98] active:brightness-[0.96] ${
                        activeChannel === it.channel ? "ring-2 ring-primary/60" : ""
                      } ${channelColorClass(it.channel)}`}
                    >
                      <div className="text-xs text-foreground/75 font-medium">{it.channel}</div>
                      <div className="mt-1 flex items-end justify-between gap-2">
                        <div className="text-lg font-semibold text-foreground tabular-nums">
                          {Math.round(it.sum).toLocaleString()}
                        </div>
                        <div className="text-xs font-semibold text-foreground/70 tabular-nums">
                          {it.pct.toFixed(1)}%
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-2 text-[11px] text-muted-foreground">
                  总UV：<span className="font-medium text-foreground tabular-nums">{Math.round(channelStats.total).toLocaleString()}</span>
                  {query.trim()
                    ? <span>（已按当前筛选计算）</span>
                    : null}
                  {activeChannel ? (
                    <span>
                      {" "}
                      · 当前筛选：<span className="font-medium text-foreground">{activeChannel}</span> 为本行最大值（再次点击卡片取消）
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="h-[min(560px,calc(100vh-280px))] overflow-auto rounded-lg border border-border/50">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-muted/80 backdrop-blur z-10">
                    <tr className="border-b">
                      {columns.map((c) =>
                        c === COL_PID ? (
                          <th
                            key={c}
                            className="text-left py-3 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap"
                          >
                            {c}
                          </th>
                        ) : (
                          <th
                            key={c}
                            role="button"
                            tabIndex={0}
                            onClick={() => onSortColumn(c)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                onSortColumn(c);
                              }
                            }}
                            className={`text-left py-3 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap cursor-pointer select-none hover:text-foreground ${
                              activeChannel === c ? `${activeColBg} text-foreground` : ""
                            }`}
                          >
                            {c}
                            {sortMark(c)}
                          </th>
                        )
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {tableRows.length === 0 ? (
                      <tr>
                        <td
                          colSpan={Math.max(columns.length, 1)}
                          className="py-10 text-center text-xs text-muted-foreground"
                        >
                          {loading
                            ? "加载中…"
                            : "暂无数据（请确认已完成产品360下载且 Excel 路径正确）"}
                        </td>
                      </tr>
                    ) : (
                      tableRows.map((r, i) => {
                        const rowMax = maxChannelsOfRow(r as any);
                        const otherNumRaw = Number(String(r["其他"] ?? "").replace(/,/g, ""));
                        const otherNum = Number.isFinite(otherNumRaw) ? otherNumRaw : 0;
                        const isOtherTop = rowMax > 0 && otherNum === rowMax;
                        const isSelected = normalizePid(r[COL_PID]) === normalizePid(selectedProductId);

                        return (
                          <tr
                            key={`${r[COL_PID]}-${i}`}
                            onClick={() => setSelectedProductId(String(r[COL_PID] ?? ""))}
                            className={`group border-b last:border-0 cursor-pointer transition-colors ${
                              isSelected ? "bg-emerald-50" : "hover:bg-accent/40"
                            }`}
                          >
                            {columns.map((c) => (
                              <td
                                key={c}
                                className={`py-2.5 px-3 text-xs whitespace-nowrap ${
                                  c === "其他" && isOtherTop
                                    ? "bg-red-100 text-red-700 font-medium group-hover:brightness-95"
                                    : c !== COL_PID && activeChannel === c
                                      ? `${activeColBg} font-medium group-hover:brightness-95`
                                      : isSelected
                                        ? ""
                                        : "group-hover:bg-accent/20"
                                }`}
                              >
                                {r[c] === "" || r[c] === undefined ? "" : String(r[c])}
                              </td>
                            ))}
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </div>

        <div className="col-span-12 lg:col-span-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">说明</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-xs text-muted-foreground leading-relaxed">
              <p>
                与「数据下载 → 产品参谋数据」共用同一份配置：请在产品参谋页填写并保存「Excel 结果路径」。本页读取该目录下的{" "}
                <span className="text-foreground font-medium">产品数据总报告.xlsx</span>。
              </p>
              <p>
                此页面意在寻找到每个产品的流量来源，从而进行优化。例如：当发现“其他”这个渠道的占比过高时，需要知道是哪些产品导致的结果
              </p>
              <p>
              <span className="text-foreground font-medium">分析流程：流量分析（确认店铺问题）---渠道数据（确认来源问题）---单品渠道数据（确认产品问题）</span>
              </p>
              {sourceFile ? (
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">当前文件</Label>
                  <div className="rounded-md border border-border/50 bg-muted/30 p-2 font-mono text-[11px] break-all text-foreground">
                    {sourceFile}
                  </div>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card className="mt-6">
            <CardHeader className="pb-3">
              <CardTitle className="text-base">直通车最近4周数据</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {!selectedProductId ? (
                <div className="h-64 rounded-lg border border-dashed border-border/60 flex items-center justify-center text-xs text-muted-foreground text-center px-6">
                  点击左侧表格中的某一行后，这里会显示对应产品ID的直通车最近4周数据
                </div>
              ) : p4pLoading ? (
                <div className="h-64 rounded-lg border border-border/50 flex items-center justify-center text-xs text-muted-foreground">
                  加载中...
                </div>
              ) : p4pRecentCols.length === 0 ? (
                <div className="h-64 rounded-lg border border-border/50 flex items-center justify-center text-xs text-muted-foreground text-center px-6">
                  未读取到该产品的直通车最近4周数据
                </div>
              ) : (
                <>
                  <div className="space-y-1">
                    <div className="text-xs text-muted-foreground">
                      产品ID：<span className="font-medium text-foreground">{selectedProductId}</span>
                    </div>
                    <div className="text-xs text-muted-foreground">
                      来源：P4P输出文件{p4pSheetName ? ` / ${p4pSheetName}` : ""}-----若无数据代表该产品没有加入P4P
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    {p4pRecentCols.map((c) => (
                      <div key={c} className="rounded-xl border border-border/60 bg-muted/20 px-3 py-3">
                        <div className="text-[11px] text-muted-foreground break-all">{c}</div>
                        <div className="mt-1 text-lg font-semibold text-foreground tabular-nums break-all">
                          {String(p4pRecentValues?.[c] ?? "") || "-"}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="text-[11px] text-muted-foreground leading-relaxed">
                    显示内容取自「综合数据分析 → 文件目录配置」中的 P4P 输出文件，固定读取「曝光量」sheet 的最近4周列。
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
