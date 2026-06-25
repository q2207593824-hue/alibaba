import { useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChevronRight, Eye, MousePointer, Users, MessageSquare, Star } from "lucide-react";
import { analysisApi, configApi, dataApi } from "@/lib/api";

const newLinksSheets = [
  "全店曝光次数", "全站推广曝光次数", "搜索曝光次数",
  "全店点击次数", "全站推广点击次数", "搜索点击次数",
  "访问人数", "询盘人数", "TM咨询人数",
];

const newLinksSearchSheets = [
  "全店曝光次数", "全站推广曝光次数", "搜索曝光次数",
  "全店点击次数", "全站推广点击次数", "搜索点击次数",
  "访问人数", "询盘人数", "TM咨询人数",
];

export default function NewLinksAnalysis() {
  const [newOutputFile, setNewOutputFile] = useState("");
  const [newLinksPath, setNewLinksPath] = useState("");
  const [newLinksData, setNewLinksData] = useState<{ columns: string[]; rows: any[]; latest_col?: string }>({ columns: [], rows: [] });
  const [daysSincePublishMap, setDaysSincePublishMap] = useState<Record<string, number>>({});
  const [longDaysLowExposureMap, setLongDaysLowExposureMap] = useState<Record<string, boolean>>({});
  const [newLinksSheet, setNewLinksSheet] = useState("全店曝光次数");
  const [newLinksSortKey, setNewLinksSortKey] = useState<string | null>(null);
  const [newLinksSortDir, setNewLinksSortDir] = useState<"asc" | "desc">("desc");

  const [newLinksProductIdQuery, setNewLinksProductIdQuery] = useState("");
  const [newLinksSearchRows, setNewLinksSearchRows] = useState<any[]>([]);
  const [newLinksSearchCols, setNewLinksSearchCols] = useState<string[]>([]);

  const [overviewStats, setOverviewStats] = useState({
    totalExposure: 0,
    totalClicks: 0,
    totalVisitors: 0,
    totalInquiry: 0,
    totalSearchExposure: 0,
  });

  const fixedCols = ["产品ID", "异动", "涨跌", "最近橱窗状态", "最近P4P状态"];

  const renderCellText = (col: string, val: any) => {
    if (col === "最近橱窗状态" || col === "最近P4P状态") {
      const s = String(val ?? "").trim().toLowerCase();
      if (["true", "y", "yes", "1", "是", "投放中"].includes(s)) return "投放中";
      if (["false", "n", "no", "0", "否", "未投放"].includes(s)) return "未投放";
      return val == null || val === "" ? "未投放" : String(val);
    }
    return String(val ?? "");
  };

  const toNumericLike = (v: any) => {
    if (v == null || v === "") return { num: 0, isNum: false };
    const s = String(v).replace(/,/g, "").replace(/%/g, "").trim();
    const n = Number(s);
    if (Number.isFinite(n)) return { num: n, isNum: true };
    return { num: 0, isNum: false };
  };

  const normalizePid = (v: any) => {
    const s = String(v ?? "").replace(/\.0+$/, "").trim();
    if (!s) return "";

    // 兼容“新发链接”里可能是完整URL（如含 itemId=160xxxx）
    const byParam = s.match(/(?:itemId=|productId=|id=)(\d{10,20})/i);
    if (byParam) return byParam[1];

    // 兼容纯产品ID或混合文本，提取最长数字串作为产品ID
    const allMatches = s.match(/\d{10,20}/g);
    if (allMatches && allMatches.length) {
      return allMatches.sort((a, b) => b.length - a.length)[0];
    }

    return s;
  };

  const parsePublishDate = (v: any): Date | null => {
    if (v == null || v === "") return null;

    if (v instanceof Date && !Number.isNaN(v.getTime())) {
      return new Date(v.getFullYear(), v.getMonth(), v.getDate());
    }

    const raw = String(v).trim();
    if (!raw) return null;

    const serial = Number(raw);
    if (Number.isFinite(serial) && serial > 20000 && serial < 80000) {
      const excelEpoch = new Date(1899, 11, 30).getTime();
      const ms = excelEpoch + Math.round(serial) * 24 * 60 * 60 * 1000;
      const dt = new Date(ms);
      if (!Number.isNaN(dt.getTime())) return new Date(dt.getFullYear(), dt.getMonth(), dt.getDate());
    }

    const s = raw.replace(/'/g, "").replace(/\.0+$/, "").trim();
    const digits = s.replace(/\D/g, "");

    if (digits.length === 6) {
      const year = 2000 + Number(digits.slice(0, 2));
      const month = Number(digits.slice(2, 4));
      const day = Number(digits.slice(4, 6));
      const dt = new Date(year, month - 1, day);
      if (dt.getFullYear() === year && dt.getMonth() === month - 1 && dt.getDate() === day) return dt;
    }

    if (digits.length === 8) {
      const year = Number(digits.slice(0, 4));
      const month = Number(digits.slice(4, 6));
      const day = Number(digits.slice(6, 8));
      const dt = new Date(year, month - 1, day);
      if (dt.getFullYear() === year && dt.getMonth() === month - 1 && dt.getDate() === day) return dt;
    }

    let m = s.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/);
    if (m) {
      const year = Number(m[1]);
      const month = Number(m[2]);
      const day = Number(m[3]);
      const dt = new Date(year, month - 1, day);
      if (dt.getFullYear() === year && dt.getMonth() === month - 1 && dt.getDate() === day) return dt;
    }

    const dt = new Date(s);
    if (!Number.isNaN(dt.getTime())) return new Date(dt.getFullYear(), dt.getMonth(), dt.getDate());

    return null;
  };

  const calcDaysSince = (date: Date): number => {
    const today = new Date();
    const start = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
    const end = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
    const diff = Math.floor((end - start) / (24 * 60 * 60 * 1000));
    return diff < 0 ? 0 : diff;
  };

  const getPublishRawFromRow = (r: any) =>
    r?.["发品日期"] ??
    r?.["发布时间"] ??
    r?.["发布日"] ??
    r?.["日期"];

  const getDaysSinceFromRow = (r: any): number | null => {
    const dt = parsePublishDate(getPublishRawFromRow(r));
    if (!dt) return null;
    return calcDaysSince(dt);
  };

  const loadConfig = async () => {
    try {
      const da = (await configApi.getSection("data_analysis")) || {};
      setNewOutputFile(da.new_output_file || "");
      setNewLinksPath(da.new_links_file_path || "");
    } catch {
      // ignore
    }
  };

  const refreshNewLinks = async (sheetName?: string) => {
    try {
      const res = await analysisApi.getNewLinksMonitor(newOutputFile || undefined, sheetName || newLinksSheet || "全店曝光次数");
      const payload = res?.data || res;
      const data = payload?.data || payload;
      setNewLinksData({
        columns: data?.columns || [],
        rows: data?.rows || [],
        latest_col: data?.latest_col,
      });

      const [expRes, clickRes, visitRes, askRes, tmRes, searchExpRes] = await Promise.all([
        analysisApi.getNewLinksMonitor(newOutputFile || undefined, "全店曝光次数"),
        analysisApi.getNewLinksMonitor(newOutputFile || undefined, "全店点击次数"),
        analysisApi.getNewLinksMonitor(newOutputFile || undefined, "访问人数"),
        analysisApi.getNewLinksMonitor(newOutputFile || undefined, "询盘人数"),
        analysisApi.getNewLinksMonitor(newOutputFile || undefined, "TM咨询人数"),
        analysisApi.getNewLinksMonitor(newOutputFile || undefined, "搜索曝光次数"),
      ]);

      const getLatestSum = (resp: any) => {
        const payloadX = resp?.data || resp;
        const d = payloadX?.data || payloadX;
        const rows: any[] = d?.rows || [];
        const latestCol = d?.latest_col as string | undefined;
        if (!latestCol) return 0;
        return rows.reduce((sum, r) => {
          const v = Number(String(r?.[latestCol] ?? "0").replace(/,/g, ""));
          return sum + (Number.isFinite(v) ? v : 0);
        }, 0);
      };

      const totalAsk = getLatestSum(askRes);
      const totalTm = getLatestSum(tmRes);
      setOverviewStats({
        totalExposure: getLatestSum(expRes),
        totalClicks: getLatestSum(clickRes),
        totalVisitors: getLatestSum(visitRes),
        totalInquiry: totalAsk + totalTm,
        totalSearchExposure: getLatestSum(searchExpRes),
      });
    } catch {
      setNewLinksData({ columns: [], rows: [] });
      setOverviewStats({
        totalExposure: 0,
        totalClicks: 0,
        totalVisitors: 0,
        totalInquiry: 0,
        totalSearchExposure: 0,
      });
      setLongDaysLowExposureMap({});
    }
  };

  useEffect(() => {
    loadConfig();
  }, []);

  useEffect(() => {
    if (!newOutputFile) return;
    refreshNewLinks(newLinksSheet || undefined);
  }, [newOutputFile, newLinksSheet]);

  useEffect(() => {
    const run = async () => {
      if (!newLinksPath) {
        setDaysSincePublishMap({});
        return;
      }
      try {
        let latestPath = "";
        const isExcelFilePath = /\.(xlsx|xls)$/i.test(String(newLinksPath).trim());

        if (isExcelFilePath) {
          latestPath = String(newLinksPath).trim();
        } else {
          const res = await dataApi.getFiles(newLinksPath);
          const payload = res?.data ?? res;
          const files = Array.isArray(payload) ? payload : payload?.data || [];
          const excelFiles = (files || [])
            .filter((f: any) => /\.(xlsx|xls)$/i.test(String(f?.name || "")))
            .filter((f: any) => !String(f?.name || "").startsWith("~$"));

          if (!excelFiles.length) {
            setDaysSincePublishMap({});
            return;
          }

          const sorted = [...excelFiles].sort((a: any, b: any) => Number(b?.modified || 0) - Number(a?.modified || 0));
          const latest = sorted[0];
          latestPath = String(latest?.path || "");
        }

        if (!latestPath) {
          setDaysSincePublishMap({});
          return;
        }

        const tableRes = await analysisApi.getNewLinksMonitor(latestPath, "全店曝光次数");
        const tablePayload = tableRes?.data || tableRes;
        const tableData = tablePayload?.data || tablePayload;
        const rows: any[] = Array.isArray(tableData?.rows) ? tableData.rows : [];

        const map: Record<string, number> = {};
        rows.forEach((r: any) => {
          const pid = normalizePid(
            r?.["产品ID"] ??
            r?.["产品id"] ??
            r?.["新发链接"] ??
            r?.["新链接"] ??
            r?.["链接"]
          );
          if (!pid) return;

          const publishRaw =
            r?.["发品日期"] ??
            r?.["发布时间"] ??
            r?.["发布日"] ??
            r?.["日期"];

          const dt = parsePublishDate(publishRaw);
          if (!dt) return;

          // 同一产品ID出现多次时，取“最新发品日期”（更接近真实发品天数）
          const days = calcDaysSince(dt);
          if (map[pid] == null || days < map[pid]) {
            map[pid] = days;
          }
        });

        setDaysSincePublishMap(map);
      } catch {
        setDaysSincePublishMap({});
      }
    };

    run();
  }, [newLinksPath]);

  useEffect(() => {
    const run = async () => {
      const q = newLinksProductIdQuery.trim();
      if (!q || !newOutputFile) {
        setNewLinksSearchCols([]);
        setNewLinksSearchRows([]);
        return;
      }

      try {
        const rows: any[] = [];
        let mergedCols: string[] = ["指标", "产品ID"];

        for (const s of newLinksSearchSheets) {
          const res = await analysisApi.getNewLinksMonitor(newOutputFile || undefined, s);
          const payload = res?.data || res;
          const data = payload?.data || payload;
          const cols: string[] = Array.isArray(data?.columns) ? data.columns : [];
          const list: any[] = Array.isArray(data?.rows) ? data.rows : [];
          const row = list.find((r: any) => String(r?.["产品ID"] ?? "").includes(q));

          const metricRow: any = { 指标: s, 产品ID: String(row?.["产品ID"] ?? q) };
          cols.forEach((c) => {
            if (c === "产品ID") return;
            metricRow[c] = row?.[c] ?? "";
          });
          rows.push(metricRow);

          const nextCols = cols.filter((c) => c !== "产品ID");
          mergedCols = [...mergedCols, ...nextCols.filter((c) => !mergedCols.includes(c))];
        }

        const weekCols = mergedCols.filter((c) => /^\d{6}-\d{6}$/.test(String(c))).sort((a, b) => String(b).localeCompare(String(a)));
        const otherCols = mergedCols.filter((c) => !["指标", "产品ID"].includes(c) && !/^\d{6}-\d{6}$/.test(String(c)));
        setNewLinksSearchCols(["指标", "产品ID", ...weekCols, ...otherCols]);
        setNewLinksSearchRows(rows);
      } catch {
        setNewLinksSearchCols(["指标", "产品ID"]);
        setNewLinksSearchRows(newLinksSearchSheets.map((name) => ({ 指标: name, 产品ID: q })));
      }
    };

    run();
  }, [newLinksProductIdQuery, newOutputFile]);

  useEffect(() => {
    const run = async () => {
      if (!newOutputFile) {
        setLongDaysLowExposureMap({});
        return;
      }

      try {
        const res = await analysisApi.getNewLinksMonitor(newOutputFile || undefined, "全店曝光次数");
        const payload = res?.data || res;
        const data = payload?.data || payload;
        const cols: string[] = Array.isArray(data?.columns) ? data.columns : [];
        const list: any[] = Array.isArray(data?.rows) ? data.rows : [];

        const weekCols = cols
          .filter((c) => /^\d{6}-\d{6}$/.test(String(c)))
          .sort((a, b) => String(b).localeCompare(String(a)))
          .slice(0, 5);

        const nextMap: Record<string, boolean> = {};

        list.forEach((r: any) => {
          const pid = normalizePid(r?.["产品ID"]);
          if (!pid) return;

          const mappedDays = daysSincePublishMap[pid];
          const fallbackDays = getDaysSinceFromRow(r);
          const days = mappedDays ?? (fallbackDays == null ? null : fallbackDays);

          // 标红逻辑：
          // 1) 发品天数 > 30
          // 2) 在“全店曝光次数”的最近5个周期中，曝光<=30的次数 >= 3
          // 满足两者才标红。
          if (days == null || days <= 30) {
            nextMap[pid] = false;
            return;
          }

          const lowCnt = weekCols.reduce((acc, c) => {
            const n = toNumericLike(r?.[c]).num;
            return acc + (n <= 30 ? 1 : 0);
          }, 0);

          nextMap[pid] = lowCnt >= 3;
        });

        setLongDaysLowExposureMap(nextMap);
      } catch {
        setLongDaysLowExposureMap({});
      }
    };

    run();
  }, [newOutputFile, daysSincePublishMap]);

  const tableCols = useMemo(() => {
    const rawCols = (newLinksData.columns.length ? newLinksData.columns : ["产品ID"]);
    const isWeekCol = (c: string) => /^\d{6}-\d{6}$/.test(String(c));
    const sortedWeeks = rawCols.filter(isWeekCol).sort((a, b) => String(b).localeCompare(String(a)));

    const orderedFixed = ["异动", "涨跌", "最近橱窗状态", "最近P4P状态"].filter((c) => rawCols.includes(c));

    const colsWeekSorted = rawCols.map((c) => {
      if (!isWeekCol(c)) return c;
      return sortedWeeks.shift() || c;
    });

    const colsWithoutFixed = colsWeekSorted.filter((c) => !orderedFixed.includes(c) && c !== "产品ID");
    const weekCols = colsWithoutFixed.filter((c) => isWeekCol(c));
    const latestWeekCol = weekCols.length ? weekCols[0] : "";

    if (!latestWeekCol) return ["产品ID", ...orderedFixed, ...colsWithoutFixed];

    const latestIndex = colsWithoutFixed.findIndex((c) => c === latestWeekCol);
    if (latestIndex < 0) return ["产品ID", ...orderedFixed, ...colsWithoutFixed];

    const withDays = [...colsWithoutFixed];
    withDays.splice(latestIndex, 0, "发品天数");
    return ["产品ID", ...orderedFixed, ...withDays];
  }, [newLinksData.columns]);

  const canSortCol = (c: string) => !["产品ID", "最近橱窗状态", "最近P4P状态"].includes(c);
  const sortMark = (c: string) => (newLinksSortKey === c ? (newLinksSortDir === "asc" ? "↑" : "↓") : "");
  const onSortCol = (c: string) => {
    if (!canSortCol(c)) return;
    if (newLinksSortKey === c) {
      setNewLinksSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setNewLinksSortKey(c);
      setNewLinksSortDir("desc");
    }
  };

  const rows = useMemo(() => {
    const rowsRaw = newLinksData.rows || [];
    return [...rowsRaw].sort((a: any, b: any) => {
      if (!newLinksSortKey) return 0;

      if (newLinksSortKey === "发品天数") {
        const apid = normalizePid(a?.["产品ID"]);
        const bpid = normalizePid(b?.["产品ID"]);
        const aFromMap = daysSincePublishMap[apid];
        const bFromMap = daysSincePublishMap[bpid];
        const aFromRow = getDaysSinceFromRow(a);
        const bFromRow = getDaysSinceFromRow(b);
        const av = (aFromMap ?? aFromRow ?? -1);
        const bv = (bFromMap ?? bFromRow ?? -1);
        return newLinksSortDir === "asc" ? av - bv : bv - av;
      }

      const avRaw = a?.[newLinksSortKey];
      const bvRaw = b?.[newLinksSortKey];
      const av = toNumericLike(avRaw);
      const bv = toNumericLike(bvRaw);
      if (av.isNum || bv.isNum) {
        return newLinksSortDir === "asc" ? av.num - bv.num : bv.num - av.num;
      }
      const as = String(avRaw ?? "");
      const bs = String(bvRaw ?? "");
      return newLinksSortDir === "asc" ? as.localeCompare(bs) : bs.localeCompare(as);
    });
  }, [newLinksData.rows, newLinksSortKey, newLinksSortDir, daysSincePublishMap]);

  const topCards = [
    { label: "总曝光", value: overviewStats.totalExposure, icon: Eye, color: "text-blue-600", bg: "from-blue-50 to-white" },
    { label: "总点击", value: overviewStats.totalClicks, icon: MousePointer, color: "text-emerald-600", bg: "from-emerald-50 to-white" },
    { label: "总访客", value: overviewStats.totalVisitors, icon: Users, color: "text-amber-600", bg: "from-amber-50 to-white" },
    { label: "总询盘", value: overviewStats.totalInquiry, icon: MessageSquare, color: "text-violet-600", bg: "from-violet-50 to-white" },
    { label: "搜索曝光", value: overviewStats.totalSearchExposure, icon: Star, color: "text-rose-600", bg: "from-rose-50 to-white" },
  ];

  const stickyLeftMap: Record<string, string> = {
    "产品ID": "left-0",
    "异动": "left-[170px]",
    "涨跌": "left-[270px]",
    "最近橱窗状态": "left-[360px]",
    "最近P4P状态": "left-[490px]",
  };

  const fixedWidthMap: Record<string, string> = {
    "产品ID": "w-[170px] min-w-[170px]",
    "异动": "w-[100px] min-w-[100px]",
    "涨跌": "w-[90px] min-w-[90px]",
    "最近橱窗状态": "w-[130px] min-w-[130px]",
    "最近P4P状态": "w-[130px] min-w-[130px]",
  };

  return (
    <div className="p-8">
      <div className="mb-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>数据分析</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">新发链接监控</span>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">新发链接监控</h1>
            <p className="text-sm text-muted-foreground mt-1">从综合分析中拆分出的独立新发链接监控页面</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-5 gap-4 mb-6">
        {topCards.map((card) => (
          <Card key={card.label} className={`bg-gradient-to-br ${card.bg}`}>
            <CardContent className="py-4">
              <div className="flex items-center gap-2 mb-2">
                <card.icon className={`w-4 h-4 ${card.color}`} />
                <span className="text-xs text-muted-foreground">{card.label}</span>
              </div>
              <div className="text-xl font-bold">{Math.round(card.value).toLocaleString()}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between gap-3">
            <CardTitle className="text-base">新发链接数据监控</CardTitle>
            <div className="flex items-center gap-2">
              <Input
                value={newLinksProductIdQuery}
                onChange={(e) => setNewLinksProductIdQuery(e.target.value)}
                placeholder="搜索产品ID（支持包含匹配）"
                className="h-8 w-56 text-xs"
              />
              <select
                className="h-8 rounded border border-input bg-background px-2 text-xs"
                value={newLinksSheet}
                onChange={(e) => setNewLinksSheet(e.target.value)}
              >
                {newLinksSheets.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <Button size="sm" variant="outline" onClick={() => refreshNewLinks(newLinksSheet || undefined)}>刷新</Button>
            </div>
          </div>
          <div className="mt-2 flex justify-center">
            <div className="inline-flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-2.5 py-1 text-xs text-red-700 text-center">
              <span className="inline-block h-2 w-2 rounded-full bg-red-500" />
              <span>红色行说明：发品天数 &gt; 30 且「全店曝光次数」最近5个周期中，曝光≤30 的周期数 ≥ 3。</span>
            </div>
          </div>
        </CardHeader>

        <CardContent>
          <div className={`${newLinksProductIdQuery.trim() ? "h-[280px]" : "h-[560px]"} overflow-auto rounded-lg border border-border/50`}>
            {newLinksProductIdQuery.trim() ? (
              <table className="min-w-max text-sm">
                <thead className="sticky top-0 z-20 bg-muted/90 backdrop-blur">
                  <tr className="border-b bg-muted/90">
                    {(newLinksSearchCols.length ? newLinksSearchCols : ["指标", "产品ID"]).map((c) => {
                      const isFixed = c === "指标" || c === "产品ID";
                      return (
                        <th
                          key={c}
                          className={`text-left py-2 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap ${isFixed ? "sticky left-0 z-30 bg-muted/90" : ""}`}
                        >
                          {c}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {(newLinksSearchRows.length ? newLinksSearchRows : newLinksSearchSheets.map((name) => ({ 指标: name, 产品ID: newLinksProductIdQuery.trim() }))).map((row: any, idx: number) => (
                    <tr key={`new-links-search-${idx}`} className="border-b last:border-0 hover:bg-accent/30 transition-colors">
                      {(newLinksSearchCols.length ? newLinksSearchCols : ["指标", "产品ID"]).map((c) => (
                        <td key={c} className="py-2 px-3 text-xs whitespace-nowrap">
                          {String(row?.[c] ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <table className="min-w-max text-sm">
                <thead className="sticky top-0 z-20 bg-muted/90 backdrop-blur">
                  <tr className="h-9 border-b bg-muted/30">
                    {tableCols.map((c) => {
                      const isFixed = fixedCols.includes(c);
                      const leftCls = stickyLeftMap[c] || "";
                      return (
                        <th
                          key={c}
                          className={`text-left px-3 text-xs font-medium text-muted-foreground whitespace-nowrap ${fixedWidthMap[c] || ""} ${canSortCol(c) ? "cursor-pointer select-none" : ""} ${isFixed ? `sticky ${leftCls} z-30 bg-muted/90` : ""}`}
                          onClick={() => onSortCol(c)}
                        >
                          {c}{sortMark(c) ? ` ${sortMark(c)}` : ""}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {rows.length === 0 ? (
                    <tr>
                      <td colSpan={Math.max(tableCols.length, 1)} className="py-10 text-center text-xs text-muted-foreground">暂无新发链接监控数据</td>
                    </tr>
                  ) : rows.map((row: any, idx: number) => {
                    const pid = normalizePid(row?.["产品ID"]);
                    const shouldWarn = !!longDaysLowExposureMap[pid];
                    return (
                      <tr
                        key={`nl-${idx}`}
                        className={`h-8 border-b last:border-0 transition-colors ${shouldWarn ? "bg-red-100/70 hover:bg-red-100/80" : "hover:bg-accent/30"}`}
                      >
                        {tableCols.map((c) => {
                          const isFixed = fixedCols.includes(c);
                          const leftCls = stickyLeftMap[c] || "";
                          const displayVal = c === "发品天数"
                            ? (() => {
                                const pid = normalizePid(row?.["产品ID"]);
                                const mapped = daysSincePublishMap[pid];
                                if (mapped != null) return String(mapped);
                                const fallback = getDaysSinceFromRow(row);
                                return fallback == null ? "" : String(fallback);
                              })()
                            : renderCellText(c, row?.[c]);
                          return (
                            <td
                              key={c}
                              className={`h-8 py-0 px-3 text-xs whitespace-nowrap align-middle ${isFixed ? `sticky ${leftCls} z-10 bg-background` : ""}`}
                            >
                              {displayVal}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
