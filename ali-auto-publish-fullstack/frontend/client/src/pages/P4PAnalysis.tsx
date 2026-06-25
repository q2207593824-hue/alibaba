import { useEffect, useMemo, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChevronRight, Eye, MousePointer, Users, MessageSquare, Star } from "lucide-react";
import { analysisApi, configApi, dataApi } from "@/lib/api";

const P4P_PAGE_CACHE_KEY = "p4p_analysis_page_cache_v1";

export default function P4PAnalysis() {
  const [p4pOutputFile, setP4pOutputFile] = useState("");
  const [p4pSourceDir, setP4pSourceDir] = useState("");
  const [product360ExcelDir, setProduct360ExcelDir] = useState("");

  const [p4pData, setP4pData] = useState<{ sheet: string; sheets: string[]; columns: string[]; rows: any[] }>({ sheet: "", sheets: [], columns: [], rows: [] });
  const [p4pSheet, setP4pSheet] = useState("");
  const [p4pSortKey, setP4pSortKey] = useState<string>("计划ID");
  const [p4pSortDir, setP4pSortDir] = useState<"asc" | "desc">("desc");
  const [p4pUseAbsDefaultSort, setP4pUseAbsDefaultSort] = useState(true);
  const [p4pProductIdQuery, setP4pProductIdQuery] = useState("");
  const [p4pSearchRows, setP4pSearchRows] = useState<any[]>([]);
  const [p4pSearchCols, setP4pSearchCols] = useState<string[]>([]);
  const [detailInfoRows, setDetailInfoRows] = useState<any[]>([]);
  const [keywordRows, setKeywordRows] = useState<any[]>([]);
  const [regionRows, setRegionRows] = useState<any[]>([]);
  const [trafficSourceRows, setTrafficSourceRows] = useState<Array<{ item: string }>>([]);
  const [p4pOverviewStats, setP4pOverviewStats] = useState({ exposure: 0, clicks: 0, opportunities: 0, inquiry: 0, tm: 0 });

  const [latestFileName, setLatestFileName] = useState("");
  const [latestRowsRaw, setLatestRowsRaw] = useState<any[]>([]);
  const [latestSortKey, setLatestSortKey] = useState<string>("曝光量");
  const [latestSortDir, setLatestSortDir] = useState<"asc" | "desc">("desc");
  const [trafficChannelTableRemote, setTrafficChannelTableRemote] = useState<{ columns: string[]; rows: any[] }>({ columns: ["产品ID"], rows: [] });
  const [trafficSortKey, setTrafficSortKey] = useState<string>("其他");
  const [trafficSortDir, setTrafficSortDir] = useState<"asc" | "desc">("desc");

  const [withInquirySortKey, setWithInquirySortKey] = useState<string>("全站商机量");
  const [withInquirySortDir, setWithInquirySortDir] = useState<"asc" | "desc">("desc");
  const [lowClickSortKey, setLowClickSortKey] = useState<string>("点击率");
  const [lowClickSortDir, setLowClickSortDir] = useState<"asc" | "desc">("desc");

  const latestCols = [
    "产品ID",
    "计划ID",
    "曝光量",
    "点击量",
    "点击率",
    "全站商机量",
    "L1+全站商机量",
    "全站商机转化率",
    "L1+点击量",
    "L1+买家点击占比",
  ];

  // 右侧“有询盘”展示关键列
  const rightCols = [
    "产品ID",
    "计划ID",
    "曝光量",
    "点击量",
    "点击率",
    "全站商机量",
    "L1+全站商机量",
    "全站商机转化率",
  ];

  // 右侧“无询盘且点击率低”不显示商机相关三列
  const lowClickCols = [
    "产品ID",
    "计划ID",
    "曝光量",
    "点击量",
    "点击率",
  ];

  const percentColumns = new Set(["点击率", "全站商机转化率", "L1+买家点击占比"]);

  const toNumericLike = (v: any) => {
    if (v == null || v === "") return { num: 0, isNum: false };
    const s = String(v).replace(/,/g, "").replace(/%/g, "").trim();
    const n = Number(s);
    if (Number.isFinite(n)) return { num: n, isNum: true };
    return { num: 0, isNum: false };
  };

  const formatPercentCell = (v: any) => {
    if (v == null || v === "") return "";
    const raw = String(v).trim();
    const hadPercent = raw.includes("%");
    const parsed = toNumericLike(v);
    if (!parsed.isNum) return raw;
    const base = hadPercent ? parsed.num : (Math.abs(parsed.num) <= 1 ? parsed.num * 100 : parsed.num);
    return `${base.toFixed(2)}%`;
  };

  // 统一“百分比口径”数值：0.0725 -> 7.25，7.25 -> 7.25，"7.25%" -> 7.25
  const toPercentValue = (v: any) => {
    const raw = String(v ?? "").trim();
    const hadPercent = raw.includes("%");
    const parsed = toNumericLike(v);
    if (!parsed.isNum) return 0;
    return hadPercent ? parsed.num : (Math.abs(parsed.num) <= 1 ? parsed.num * 100 : parsed.num);
  };

  const formatLatestCell = (col: string, value: any) => {
    if (percentColumns.has(col)) return formatPercentCell(value);
    return String(value ?? "");
  };

  const normalizePid = (v: any) => String(v ?? "").replace(/\.0+$/, "").trim();

  const readPageCache = () => {
    try {
      const raw = localStorage.getItem(P4P_PAGE_CACHE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  };

  const writePageCache = (patch: Record<string, any>) => {
    try {
      const prev = readPageCache() || {};
      localStorage.setItem(P4P_PAGE_CACHE_KEY, JSON.stringify({
        ...prev,
        ...patch,
        updatedAt: Date.now(),
      }));
    } catch {
      // ignore
    }
  };

  // 说明：流量渠道表数据在后端按产品ID筛选并聚合，避免前端加载整张“流量来源”sheet造成卡顿

  const loadConfig = async () => {
    try {
      const sections = await configApi.getSections(["data_analysis", "data_download"]);
      const da = sections.data_analysis || {};
      const dd = sections.data_download || {};
      setP4pOutputFile(da.p4p_output_file || "");
      setP4pSourceDir(da.p4p_source_dir || "");
      setProduct360ExcelDir(dd.product360_excel_result_dir || "");
    } catch {
      // ignore
    }
  };

  const refreshLatestP4pFileTable = async () => {
    try {
      if (!p4pSourceDir) {
        setLatestRowsRaw([]);
        setLatestFileName("");
        return;
      }

      const filesRes = await dataApi.getFiles(p4pSourceDir);
      const filesPayload = filesRes?.data ?? filesRes;
      const files = Array.isArray(filesPayload) ? filesPayload : filesPayload?.data || [];
      const excelFiles = (files || [])
        .filter((f: any) => /\.(xlsx|xls)$/i.test(String(f?.name || "")))
        .filter((f: any) => !String(f?.name || "").startsWith("~$"));
      if (!excelFiles.length) {
        setLatestRowsRaw([]);
        setLatestFileName("");
        return;
      }

      const parseWeekEnd = (name: string) => {
        const m = String(name || "").match(/(\d{6})-(\d{6})\.xlsx$/i);
        if (!m) return 0;
        return Number(m[2]) || 0;
      };

      const sorted = [...excelFiles].sort((a: any, b: any) => {
        const ae = parseWeekEnd(String(a?.name || ""));
        const be = parseWeekEnd(String(b?.name || ""));
        if (ae !== be) return be - ae;
        return Number(b?.modified || 0) - Number(a?.modified || 0);
      });
      const latest = sorted[0];
      const latestPath = String(latest?.path || "");
      setLatestFileName(String(latest?.name || ""));

      const tableRes = await analysisApi.getP4pTable(latestPath || undefined, undefined);
      const payload = tableRes?.data || tableRes;
      const data = payload?.data || payload;
      const rows = Array.isArray(data?.rows) ? data.rows : [];
      const cols: string[] = Array.isArray(data?.columns) ? data.columns : [];

      const byNameOrIndex = (row: any, names: string[], idx?: number) => {
        for (const n of names) {
          if (n in (row || {})) return row?.[n];
        }
        if (typeof idx === "number" && idx >= 0 && idx < cols.length) {
          const k = cols[idx];
          return k ? row?.[k] : undefined;
        }
        return undefined;
      };

      const mapped = rows
        .map((r: any) => {
          const exposure = toNumericLike(byNameOrIndex(r, ["曝光量"], 8)).num;
          return {
            "产品ID": normalizePid(byNameOrIndex(r, ["产品ID"], 0)),
            "计划ID": String(byNameOrIndex(r, ["计划ID"], 2) ?? "").trim(),
            "曝光量": exposure,
            "点击量": toNumericLike(byNameOrIndex(r, ["点击量"], 9)).num,
            "点击率": byNameOrIndex(r, ["点击率"], 10) ?? "",
            "全站商机量": toNumericLike(byNameOrIndex(r, ["全站商机量"], 11)).num,
            "L1+全站商机量": toNumericLike(byNameOrIndex(r, ["L1+全站商机量"], 12)).num,
            "全站商机转化率": byNameOrIndex(r, ["全站商机转化率"], 13) ?? "",
            "L1+点击量": toNumericLike(byNameOrIndex(r, ["L1+点击量"], 14)).num,
            "L1+买家点击占比": byNameOrIndex(r, ["L1+买家点击占比"], 15) ?? "",
          };
        })
        .filter((r: any) => Number(r?.["曝光量"] || 0) >= 60);

      setLatestRowsRaw(mapped);
      writePageCache({ latestRowsRaw: mapped, latestFileName: String(latest?.name || "") });
    } catch {
      setLatestRowsRaw([]);
      setLatestFileName("");
    }
  };

  const refreshP4p = async (sheetName?: string) => {
    try {
      const res = await analysisApi.getP4pTable(p4pOutputFile || undefined, sheetName || p4pSheet || undefined);
      const payload = res?.data || res;
      const data = payload?.data || payload;
      const nextData = {
        sheet: data?.sheet || "",
        sheets: data?.sheets || [],
        columns: data?.columns || [],
        rows: data?.rows || [],
      };
      setP4pData(nextData);
      writePageCache({ p4pData: nextData });

      const sheets: string[] = data?.sheets || [];
      const preferred = sheets.includes("曝光量") ? "曝光量" : "";
      if (!sheetName && !p4pSheet && preferred) {
        setP4pSheet(preferred);
      } else if (!p4pSheet && data?.sheet) {
        setP4pSheet(data.sheet);
      }
    } catch {
      setP4pData({ sheet: "", sheets: [], columns: [], rows: [] });
    }
  };

  const refreshOverview = async () => {
    try {
      const [expRes, clickRes, oppRes, inqRes, tmRes] = await Promise.all([
        analysisApi.getP4pTable(p4pOutputFile || undefined, "曝光量"),
        analysisApi.getP4pTable(p4pOutputFile || undefined, "点击量"),
        analysisApi.getP4pTable(p4pOutputFile || undefined, "全站商机量"),
        analysisApi.getP4pTable(p4pOutputFile || undefined, "全站商机-询盘量"),
        analysisApi.getP4pTable(p4pOutputFile || undefined, "全站商机-TM咨询量"),
      ]);

      const getLatestSumP4p = (resp: any) => {
        const payloadX = resp?.data || resp;
        const d = payloadX?.data || payloadX;
        const cols: string[] = d?.columns || [];
        const rows: any[] = d?.rows || [];
        const weekCols = cols.filter((c) => /^\d{6}(?:-\d{6})?$/.test(String(c))).sort((a, b) => String(a).localeCompare(String(b)));
        const latestCol = weekCols.length ? weekCols[weekCols.length - 1] : null;
        if (!latestCol) return 0;
        return rows.reduce((sum, r) => {
          const v = Number(String(r?.[latestCol] ?? "0").replace(/,/g, ""));
          return sum + (Number.isFinite(v) ? v : 0);
        }, 0);
      };

      const nextStats = {
        exposure: getLatestSumP4p(expRes),
        clicks: getLatestSumP4p(clickRes),
        opportunities: getLatestSumP4p(oppRes),
        inquiry: getLatestSumP4p(inqRes),
        tm: getLatestSumP4p(tmRes),
      };
      setP4pOverviewStats(nextStats);
      writePageCache({ p4pOverviewStats: nextStats });
    } catch {
      // 保留已有概览统计
    }
  };

  useEffect(() => {
    const cached = readPageCache();
    if (cached?.p4pData) setP4pData(cached.p4pData);
    if (cached?.p4pOverviewStats) setP4pOverviewStats(cached.p4pOverviewStats);
    if (Array.isArray(cached?.latestRowsRaw)) setLatestRowsRaw(cached.latestRowsRaw);
    if (typeof cached?.latestFileName === "string") setLatestFileName(cached.latestFileName);
    if (cached?.trafficChannelTableRemote) setTrafficChannelTableRemote(cached.trafficChannelTableRemote);
    loadConfig();
  }, []);

  useEffect(() => {
    if (!p4pOutputFile) return;
    refreshOverview();
    refreshP4p(p4pSheet || undefined);
  }, [p4pOutputFile, p4pSheet]);

  useEffect(() => {
    if (!p4pSourceDir) return;
    refreshLatestP4pFileTable();
  }, [p4pSourceDir]);

  const p4pRawCols = p4pData.columns.length ? p4pData.columns : ["产品ID"];
  const p4pWeekCols = p4pRawCols.filter((c) => /^\d{6}-\d{6}$/.test(String(c))).sort((a, b) => String(b).localeCompare(String(a)));
  const p4pOtherCols = p4pRawCols.filter((c) => c !== "产品ID" && !/^\d{6}-\d{6}$/.test(String(c)));
  const p4pDisplayCols = [
    ...(p4pRawCols.includes("产品ID") ? ["产品ID"] : []),
    ...p4pWeekCols,
    ...p4pOtherCols,
  ];

  const p4pCanSort = (c: string) => c !== "产品ID";
  const p4pSortMark = (c: string) => (p4pSortKey === c ? (p4pSortDir === "asc" ? "↑" : "↓") : "");
  const p4pOnSort = (c: string) => {
    if (!p4pCanSort(c)) return;
    setP4pUseAbsDefaultSort(false);
    if (p4pSortKey === c) setP4pSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setP4pSortKey(c);
      setP4pSortDir("desc");
    }
  };

  const p4pDefaultDateCol = p4pWeekCols.length ? p4pWeekCols[0] : "";
  const p4pEffectiveSortKey = p4pUseAbsDefaultSort && p4pDefaultDateCol ? p4pDefaultDateCol : p4pSortKey;

  const p4pRowsFiltered = useMemo(() => {
    const q = p4pProductIdQuery.trim();
    const rows = [...(p4pData.rows || [])];
    if (!q) return rows;
    return rows.filter((r: any) => String(r?.["产品ID"] ?? "").includes(q));
  }, [p4pData.rows, p4pProductIdQuery]);

  const p4pSortedRows = [...p4pRowsFiltered].sort((a: any, b: any) => {
    if (!p4pEffectiveSortKey || !p4pCanSort(p4pEffectiveSortKey)) return 0;

    const avRaw = a?.[p4pEffectiveSortKey];
    const bvRaw = b?.[p4pEffectiveSortKey];
    const av = toNumericLike(avRaw);
    const bv = toNumericLike(bvRaw);

    if (av.isNum || bv.isNum) {
      const left = p4pUseAbsDefaultSort && p4pEffectiveSortKey === p4pDefaultDateCol ? Math.abs(av.num) : av.num;
      const right = p4pUseAbsDefaultSort && p4pEffectiveSortKey === p4pDefaultDateCol ? Math.abs(bv.num) : bv.num;
      return p4pSortDir === "asc" ? left - right : right - left;
    }

    const as = String(avRaw ?? "");
    const bs = String(bvRaw ?? "");
    return p4pSortDir === "asc" ? as.localeCompare(bs) : bs.localeCompare(as);
  });

  // 搜索产品ID时，固定展示4行：曝光量 / 点击量 / 全站商机-询盘量 / 全站商机-TM咨询量
  useEffect(() => {
    const run = async () => {
      const q = p4pProductIdQuery.trim();
      if (!q || !p4pOutputFile) {
        setP4pSearchCols([]);
        setP4pSearchRows([]);
        setDetailInfoRows([]);
        setKeywordRows([]);
        setRegionRows([]);
        setTrafficSourceRows([]);
        return;
      }

      try {
        const sheets = ["曝光量", "点击量", "全站商机-询盘量", "全站商机-TM咨询量"];
        const rows: any[] = [];
        let mergedCols: string[] = ["指标", "产品ID"];

        for (const s of sheets) {
          const res = await analysisApi.getP4pTable(p4pOutputFile || undefined, s);
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

        // 周期列按“最新 -> 最旧”展示
        const weekCols = mergedCols.filter((c) => /^\d{6}-\d{6}$/.test(String(c))).sort((a, b) => String(b).localeCompare(String(a)));
        const otherCols = mergedCols.filter((c) => !["指标", "产品ID"].includes(c) && !/^\d{6}-\d{6}$/.test(String(c)));
        setP4pSearchCols(["指标", "产品ID", ...weekCols, ...otherCols]);
        setP4pSearchRows(rows);

        if (product360ExcelDir) {
          const detailRes = await dataApi.getProduct360Table(product360ExcelDir, "产品详细信息");
          const detailPayload = detailRes?.data || detailRes;
          const detailData = detailPayload?.data || detailPayload;
          const detailCols: string[] = Array.isArray(detailData?.columns) ? detailData.columns : [];
          const detailList: any[] = Array.isArray(detailData?.rows) ? detailData.rows : [];
          const detailRow = detailList.find((r: any) => String(r?.["产品ID"] ?? "").includes(q));
          const getDetail = (name: string, idx: number) => {
            if (detailRow && name in detailRow) return detailRow?.[name];
            const k = detailCols[idx];
            return k ? detailRow?.[k] : "";
          };
          setDetailInfoRows([{
            "平台内部产品分级": getDetail("平台内部产品分级", 3),
            "产品综合搜索排名": getDetail("产品综合搜索排名", 4),
            "平台曝光标签": getDetail("平台曝光标签", 5),
            "平台访客流量标签": getDetail("平台访客流量标签", 6),
            "平台点击效率标签": getDetail("平台点击效率标签", 7),
            "平台转化效果标签": getDetail("平台转化效果标签", 8),
          }]);

          const kwRes = await dataApi.getProduct360Table(product360ExcelDir, "关键词");
          const kwPayload = kwRes?.data || kwRes;
          const kwData = kwPayload?.data || kwPayload;
          const kwCols: string[] = Array.isArray(kwData?.columns) ? kwData.columns : [];
          const kwList: any[] = Array.isArray(kwData?.rows) ? kwData.rows : [];
          const kwMatched = kwList.filter((r: any) => String(r?.["产品ID"] ?? "").includes(q));
          const getKw = (row: any, name: string, idx: number) => {
            if (name in (row || {})) return row?.[name];
            const k = kwCols[idx];
            return k ? row?.[k] : "";
          };
          setKeywordRows(kwMatched.map((r: any) => {
            const inquiry = Number(String(getKw(r, "店内询盘人数", 4) ?? "0").replace(/,/g, "")) || 0;
            const tm = Number(String(getKw(r, "店内TM咨询人数", 5) ?? "0").replace(/,/g, "")) || 0;
            return {
              "关键词": getKw(r, "关键词", 1),
              "搜索曝光次数": getKw(r, "搜索曝光次数", 2),
              "搜索点击次数": getKw(r, "搜索点击次数", 3),
              "询盘": inquiry + tm,
            };
          }));

          const regionRes = await dataApi.getProduct360Table(product360ExcelDir, "访客地域");
          const regionPayload = regionRes?.data || regionRes;
          const regionData = regionPayload?.data || regionPayload;
          const regionCols: string[] = Array.isArray(regionData?.columns) ? regionData.columns : [];
          const regionList: any[] = Array.isArray(regionData?.rows) ? regionData.rows : [];
          const getRegion = (row: any, name: string, idx: number) => {
            if (name in (row || {})) return row?.[name];
            const k = regionCols[idx];
            return k ? row?.[k] : "";
          };
          const regionMatched = regionList.filter((r: any) => String(r?.["产品ID"] ?? "").includes(q));
          setRegionRows(regionMatched.map((r: any) => ({
            "国家(中文)": getRegion(r, "国家(中文)", 1),
            "访客数(UV)": getRegion(r, "访客数(UV)", 2),
          })));

          const trafficRaw = String(getDetail("各流量渠道UV分布", 9) || "");
          const split = trafficRaw.split(";").map((s) => s.trim()).filter(Boolean).map((item) => ({ item }));
          setTrafficSourceRows(split);
        }
      } catch {
        setP4pSearchCols(["指标", "产品ID"]);
        setP4pSearchRows([
          { 指标: "曝光量", 产品ID: q },
          { 指标: "点击量", 产品ID: q },
          { 指标: "全站商机-询盘量", 产品ID: q },
          { 指标: "全站商机-TM咨询量", 产品ID: q },
        ]);
      }
    };

    run();
  }, [p4pProductIdQuery, p4pOutputFile, product360ExcelDir]);

  const latestCanSort = (c: string) => c !== "产品ID";
  const latestSortMark = (c: string) => (latestSortKey === c ? (latestSortDir === "asc" ? "↑" : "↓") : "");
  const latestOnSort = (c: string) => {
    if (!latestCanSort(c)) return;
    if (latestSortKey === c) setLatestSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setLatestSortKey(c);
      setLatestSortDir("desc");
    }
  };

  const latestRows = useMemo(() => {
    const rows = [...latestRowsRaw];
    if (!latestSortKey) return rows;
    rows.sort((a: any, b: any) => {
      const avRaw = a?.[latestSortKey];
      const bvRaw = b?.[latestSortKey];
      const av = toNumericLike(avRaw);
      const bv = toNumericLike(bvRaw);
      if (av.isNum || bv.isNum) {
        return latestSortDir === "asc" ? av.num - bv.num : bv.num - av.num;
      }
      const as = String(avRaw ?? "");
      const bs = String(bvRaw ?? "");
      return latestSortDir === "asc" ? as.localeCompare(bs) : bs.localeCompare(as);
    });
    return rows;
  }, [latestRowsRaw, latestSortKey, latestSortDir]);

  useEffect(() => {
    const run = async () => {
      if (!product360ExcelDir) {
        setTrafficChannelTableRemote({ columns: ["产品ID"], rows: [] });
        return;
      }
      const pids = (latestRows || []).map((r: any) => normalizePid(r?.["产品ID"])).filter(Boolean);
      if (!pids.length) {
        setTrafficChannelTableRemote({ columns: ["产品ID"], rows: [] });
        return;
      }
      try {
        const res = await dataApi.getProduct360TrafficChannels(product360ExcelDir, pids);
        const payload = res?.data || res;
        const data = payload?.data || payload;
        const cols: string[] = Array.isArray(data?.columns) ? data.columns : ["产品ID"];
        const rows: any[] = Array.isArray(data?.rows) ? data.rows : [];
        setTrafficChannelTableRemote({ columns: cols.length ? cols : ["产品ID"], rows });
        writePageCache({
          trafficChannelTableRemote: {
            columns: cols.length ? cols : ["产品ID"],
            rows,
          },
        });
      } catch {
        setTrafficChannelTableRemote({ columns: ["产品ID"], rows: [] });
      }
    };
    run();
  }, [product360ExcelDir, latestRows]);

  const trafficChannelTable = useMemo(() => {
    const baseRows = latestRows || [];
    if (!baseRows.length) return { columns: ["产品ID"], rows: [] as any[] };

    const cols = Array.isArray(trafficChannelTableRemote.columns) && trafficChannelTableRemote.columns.length
      ? trafficChannelTableRemote.columns
      : ["产品ID"];

    // 后端返回的 rows 已是按产品ID聚合后的透视表；这里按 baseRows 顺序补齐缺失产品
    const byPid: Record<string, any> = {};
    for (const r of (trafficChannelTableRemote.rows || [])) {
      const pid = normalizePid(r?.["产品ID"]);
      if (pid) byPid[pid] = r;
    }

    const rowsOut = baseRows.map((r: any) => {
      const pid = normalizePid(r?.["产品ID"]);
      const src = byPid[pid] || { 产品ID: pid };
      const out: any = { 产品ID: pid };
      for (const c of cols) {
        if (c === "产品ID") continue;
        out[c] = src?.[c] ?? "";
      }
      return out;
    });

    return { columns: cols, rows: rowsOut };
  }, [latestRows, trafficChannelTableRemote.columns, trafficChannelTableRemote.rows]);

  const trafficCanSort = (c: string) => c !== "产品ID";
  const trafficSortMark = (c: string) => (trafficSortKey === c ? (trafficSortDir === "asc" ? "↑" : "↓") : "");
  const onTrafficSort = (c: string) => {
    if (!trafficCanSort(c)) return;
    if (trafficSortKey === c) setTrafficSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setTrafficSortKey(c);
      setTrafficSortDir("desc");
    }
  };

  const trafficChannelSortedRows = useMemo(() => {
    const rows = [...(trafficChannelTable.rows || [])];
    if (!trafficSortKey || !trafficCanSort(trafficSortKey)) return rows;
    rows.sort((a: any, b: any) => {
      const avRaw = a?.[trafficSortKey];
      const bvRaw = b?.[trafficSortKey];
      const av = toNumericLike(avRaw);
      const bv = toNumericLike(bvRaw);
      if (av.isNum || bv.isNum) {
        return trafficSortDir === "asc" ? av.num - bv.num : bv.num - av.num;
      }
      const as = String(avRaw ?? "");
      const bs = String(bvRaw ?? "");
      return trafficSortDir === "asc" ? as.localeCompare(bs) : bs.localeCompare(as);
    });
    return rows;
  }, [trafficChannelTable.rows, trafficSortKey, trafficSortDir]);

  const rightCanSort = (c: string) => c !== "产品ID" && c !== "计划ID";
  const withInquirySortMark = (c: string) => (withInquirySortKey === c ? (withInquirySortDir === "asc" ? "↑" : "↓") : "");
  const lowClickSortMark = (c: string) => (lowClickSortKey === c ? (lowClickSortDir === "asc" ? "↑" : "↓") : "");

  const onWithInquirySort = (c: string) => {
    if (!rightCanSort(c)) return;
    if (withInquirySortKey === c) setWithInquirySortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setWithInquirySortKey(c);
      setWithInquirySortDir("desc");
    }
  };

  const onLowClickSort = (c: string) => {
    if (!rightCanSort(c)) return;
    if (lowClickSortKey === c) setLowClickSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setLowClickSortKey(c);
      setLowClickSortDir("desc");
    }
  };

  const withInquiryRows = useMemo(() => {
    const rows = [...latestRowsRaw].filter((r: any) => toNumericLike(r?.["全站商机量"]).num >= 1);
    rows.sort((a: any, b: any) => {
      const avRaw = a?.[withInquirySortKey];
      const bvRaw = b?.[withInquirySortKey];
      const av = toNumericLike(avRaw);
      const bv = toNumericLike(bvRaw);
      if (av.isNum || bv.isNum) {
        return withInquirySortDir === "asc" ? av.num - bv.num : bv.num - av.num;
      }
      const as = String(avRaw ?? "");
      const bs = String(bvRaw ?? "");
      return withInquirySortDir === "asc" ? as.localeCompare(bs) : bs.localeCompare(as);
    });
    return rows;
  }, [latestRowsRaw, withInquirySortKey, withInquirySortDir]);

  const lowClickNoInquiryRows = useMemo(() => {
    const rows = [...latestRowsRaw].filter((r: any) => {
      const opp = toNumericLike(r?.["全站商机量"]).num;
      const ctr = toPercentValue(r?.["点击率"]);
      return opp < 1 && ctr < 2;
    });
    rows.sort((a: any, b: any) => {
      const avRaw = a?.[lowClickSortKey];
      const bvRaw = b?.[lowClickSortKey];
      const av = toNumericLike(avRaw);
      const bv = toNumericLike(bvRaw);
      if (av.isNum || bv.isNum) {
        return lowClickSortDir === "asc" ? av.num - bv.num : bv.num - av.num;
      }
      const as = String(avRaw ?? "");
      const bs = String(bvRaw ?? "");
      return lowClickSortDir === "asc" ? as.localeCompare(bs) : bs.localeCompare(as);
    });
    return rows;
  }, [latestRowsRaw, lowClickSortKey, lowClickSortDir]);

  const topCards = [
    { label: "总曝光", value: p4pOverviewStats.exposure, icon: Eye, color: "text-blue-600", bg: "from-blue-50 to-white" },
    { label: "总点击", value: p4pOverviewStats.clicks, icon: MousePointer, color: "text-emerald-600", bg: "from-emerald-50 to-white" },
    { label: "全站商机", value: p4pOverviewStats.opportunities, icon: Users, color: "text-amber-600", bg: "from-amber-50 to-white" },
    { label: "询盘量", value: p4pOverviewStats.inquiry, icon: MessageSquare, color: "text-violet-600", bg: "from-violet-50 to-white" },
    { label: "全站商机-TM咨询量", value: p4pOverviewStats.tm, icon: Star, color: "text-rose-600", bg: "from-rose-50 to-white" },
  ];

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <div className="mb-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>数据分析</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">P4P分析</span>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">P4P分析</h1>
            <p className="text-sm text-muted-foreground mt-1">从综合分析中拆分出的独立 P4P 分析页面</p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-3 sm:gap-4 mb-6">
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

      <Card className="mb-6">
        <CardHeader className="pb-3">
          <div className="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-3">
            <CardTitle className="text-base">上周P4P数据</CardTitle>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-muted-foreground">文件：{latestFileName || "未找到"}</span>
              <Button size="sm" variant="outline" onClick={refreshLatestP4pFileTable}>刷新最近文件</Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 min-[1800px]:grid-cols-12 gap-4">
            <Card className="border border-border/60 min-[1800px]:col-span-7 min-w-0">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">当前数据（曝光量 ≥ 60）</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="h-[300px] overflow-auto rounded-lg border border-border/50">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 z-20 bg-muted/90 backdrop-blur">
                      <tr className="border-b bg-muted/90">
                        {latestCols.map((c) => {
                          const isFixed = c === "产品ID";
                          return (
                            <th
                              key={c}
                              className={`text-left py-2 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap ${isFixed ? "sticky left-0 z-30 bg-muted/90" : ""} ${latestCanSort(c) ? "cursor-pointer select-none" : ""}`}
                              onClick={() => latestOnSort(c)}
                            >
                              {c}{latestSortMark(c) ? ` ${latestSortMark(c)}` : ""}
                            </th>
                          );
                        })}
                      </tr>
                    </thead>
                    <tbody>
                      {latestRows.length === 0 ? (
                        <tr>
                          <td colSpan={latestCols.length} className="py-10 text-center text-xs text-muted-foreground">暂无最近日期P4P数据（请确认综合分析配置中的P4P数据目录）</td>
                        </tr>
                      ) : latestRows.map((row: any, idx: number) => (
                        <tr key={`latest-${idx}`} className="border-b last:border-0 hover:bg-accent/30 transition-colors">
                          {latestCols.map((c) => {
                            const isFixed = c === "产品ID";
                            return (
                              <td key={c} className={`py-2 px-3 text-xs whitespace-nowrap ${isFixed ? "sticky left-0 z-10 bg-background" : ""}`}>
                                {formatLatestCell(c, row?.[c])}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="mt-8 pt-4 border-t border-border/50">
                  <div className="text-sm font-medium mb-5">P4P产品流量渠道</div>
                  <div className="h-[300px] overflow-auto rounded-lg border border-border/50">
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 z-20 bg-muted/90 backdrop-blur">
                        <tr className="border-b bg-muted/90">
                          {trafficChannelTable.columns.map((c) => {
                            const isFixed = c === "产品ID";
                            return (
                              <th
                                key={c}
                                className={`text-left py-2 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap ${isFixed ? "sticky left-0 z-30 bg-muted/90" : ""} ${trafficCanSort(c) ? "cursor-pointer select-none" : ""}`}
                                onClick={() => onTrafficSort(c)}
                              >
                                {c}{trafficSortMark(c) ? ` ${trafficSortMark(c)}` : ""}
                              </th>
                            );
                          })}
                        </tr>
                      </thead>
                      <tbody>
                        {trafficChannelSortedRows.length === 0 ? (
                          <tr>
                            <td colSpan={trafficChannelTable.columns.length} className="py-10 text-center text-xs text-muted-foreground">
                              暂无数据（请确认“产品参谋数据”的 Excel 结果路径已配置且包含“产品详细信息”sheet）
                            </td>
                          </tr>
                        ) : trafficChannelSortedRows.map((row: any, idx: number) => {
                          const channels = trafficChannelTable.columns.filter((c) => c !== "产品ID");
                          const values = channels.map((c) => toNumericLike(row?.[c]).num);
                          const maxVal = values.length ? Math.max(...values) : 0;
                          const otherVal = toNumericLike(row?.["其他"]).num;
                          const highlight = maxVal > 0 && otherVal === maxVal;
                          return (
                            <tr
                              key={`traffic-ch-${idx}`}
                              className={`border-b last:border-0 transition-colors ${highlight ? "bg-red-50" : "hover:bg-accent/30"}`}
                            >
                              {trafficChannelTable.columns.map((c) => {
                                const isFixed = c === "产品ID";
                                return (
                                  <td key={c} className={`py-2 px-3 text-xs whitespace-nowrap ${isFixed ? `sticky left-0 z-10 ${highlight ? "bg-red-50" : "bg-background"}` : ""}`}>
                                    {formatLatestCell(c, row?.[c])}
                                  </td>
                                );
                              })}
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              </CardContent>
            </Card>

            <div className="grid grid-cols-1 min-[1200px]:grid-cols-2 min-[1800px]:grid-cols-1 gap-4 min-[1800px]:col-span-5 min-w-0">
              <Card className="border border-border/60 min-w-0">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">有询盘（全站商机量 ≥ 1）</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="h-[300px] min-[1800px]:h-[420px] overflow-auto rounded-lg border border-border/50">
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 z-20 bg-muted/90 backdrop-blur">
                        <tr className="border-b bg-muted/90">
                          {rightCols.map((c) => {
                            const isFixed = c === "产品ID";
                            return (
                              <th
                                key={c}
                                className={`text-left py-2 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap ${isFixed ? "sticky left-0 z-30 bg-muted/90" : ""} ${rightCanSort(c) ? "cursor-pointer select-none" : ""}`}
                                onClick={() => onWithInquirySort(c)}
                              >
                                {c}{withInquirySortMark(c) ? ` ${withInquirySortMark(c)}` : ""}
                              </th>
                            );
                          })}
                        </tr>
                      </thead>
                      <tbody>
                        {withInquiryRows.length === 0 ? (
                          <tr>
                            <td colSpan={rightCols.length} className="py-10 text-center text-xs text-muted-foreground">暂无有询盘数据</td>
                          </tr>
                        ) : withInquiryRows.map((row: any, idx: number) => (
                          <tr key={`with-inquiry-${idx}`} className="border-b last:border-0 hover:bg-accent/30 transition-colors">
                            {rightCols.map((c) => {
                              const isFixed = c === "产品ID";
                              return (
                                <td key={c} className={`py-2 px-3 text-xs whitespace-nowrap ${isFixed ? "sticky left-0 z-10 bg-background" : ""}`}>
                                  {formatLatestCell(c, row?.[c])}
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

              <Card className="border border-border/60">
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">无询盘且点击率低（全站商机量 &lt; 1 且 点击率 &lt; 2.00%）</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="h-[300px] overflow-auto rounded-lg border border-border/50">
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 z-20 bg-muted/90 backdrop-blur">
                        <tr className="border-b bg-muted/90">
                          {lowClickCols.map((c) => {
                            const isFixed = c === "产品ID";
                            return (
                              <th
                                key={c}
                                className={`text-left py-2 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap ${isFixed ? "sticky left-0 z-30 bg-muted/90" : ""} ${rightCanSort(c) ? "cursor-pointer select-none" : ""}`}
                                onClick={() => onLowClickSort(c)}
                              >
                                {c}{lowClickSortMark(c) ? ` ${lowClickSortMark(c)}` : ""}
                              </th>
                            );
                          })}
                        </tr>
                      </thead>
                      <tbody>
                        {lowClickNoInquiryRows.length === 0 ? (
                          <tr>
                            <td colSpan={lowClickCols.length} className="py-10 text-center text-xs text-muted-foreground">暂无无询盘且低点击率数据</td>
                          </tr>
                        ) : lowClickNoInquiryRows.map((row: any, idx: number) => (
                          <tr key={`low-click-${idx}`} className="border-b last:border-0 hover:bg-accent/30 transition-colors">
                            {lowClickCols.map((c) => {
                              const isFixed = c === "产品ID";
                              return (
                                <td key={c} className={`py-2 px-3 text-xs whitespace-nowrap ${isFixed ? "sticky left-0 z-10 bg-background" : ""}`}>
                                  {formatLatestCell(c, row?.[c])}
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
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between gap-3">
            <CardTitle className="text-base">P4P分析（P4P数据统计.xlsx）</CardTitle>
            <div className="flex items-center gap-2">
              <Input
                value={p4pProductIdQuery}
                onChange={(e) => setP4pProductIdQuery(e.target.value)}
                placeholder="搜索产品ID（支持包含匹配）"
                className="h-8 w-56 text-xs"
              />
              <select className="h-8 rounded border border-input bg-background px-2 text-xs" value={p4pSheet} onChange={(e) => setP4pSheet(e.target.value)}>
                {(p4pData.sheets || []).map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <Button size="sm" variant="outline" onClick={() => { refreshOverview(); refreshP4p(p4pSheet || undefined); }}>刷新P4P数据</Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className={`${p4pProductIdQuery.trim() ? "h-[280px]" : "h-[560px]"} overflow-auto rounded-lg border border-border/50`}>
            {p4pProductIdQuery.trim() ? (
              <table className="w-full text-sm">
                <thead className="sticky top-0 z-20 bg-muted/90 backdrop-blur">
                  <tr className="border-b bg-muted/90">
                    {(p4pSearchCols.length ? p4pSearchCols : ["指标", "产品ID"]).map((c) => {
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
                  {(p4pSearchRows.length ? p4pSearchRows : [
                    { 指标: "曝光量", 产品ID: p4pProductIdQuery.trim() },
                    { 指标: "点击量", 产品ID: p4pProductIdQuery.trim() },
                    { 指标: "全站商机-询盘量", 产品ID: p4pProductIdQuery.trim() },
                    { 指标: "全站商机-TM咨询量", 产品ID: p4pProductIdQuery.trim() },
                  ]).map((row: any, idx: number) => (
                    <tr key={`p4p-search-${idx}`} className="border-b last:border-0 hover:bg-accent/30 transition-colors">
                      {(p4pSearchCols.length ? p4pSearchCols : ["指标", "产品ID"]).map((c) => (
                        <td key={c} className="py-2 px-3 text-xs whitespace-nowrap">
                          {String(row?.[c] ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <table className="w-full text-sm">
                <thead className="sticky top-0 z-20 bg-muted/90 backdrop-blur">
                  <tr className="border-b bg-muted/90">
                    {p4pDisplayCols.map((c) => {
                      const isFixed = c === "产品ID";
                      return (
                        <th
                          key={c}
                          className={`text-left py-2 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap ${isFixed ? "sticky left-0 z-30 bg-muted/90" : ""} ${p4pCanSort(c) ? "cursor-pointer select-none" : ""}`}
                          onClick={() => p4pOnSort(c)}
                        >
                          {c}{p4pSortMark(c) ? ` ${p4pSortMark(c)}` : ""}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {p4pSortedRows.length === 0 ? (
                    <tr>
                      <td colSpan={Math.max(p4pDisplayCols.length, 1)} className="py-10 text-center text-xs text-muted-foreground">暂无P4P数据（请先执行综合分析）</td>
                    </tr>
                  ) : p4pSortedRows.map((row: any, idx: number) => (
                    <tr key={`p4p-${idx}`} className="border-b last:border-0 hover:bg-accent/30 transition-colors">
                      {p4pDisplayCols.map((c) => {
                        const isFixed = c === "产品ID";
                        return (
                          <td key={c} className={`py-2 px-3 text-xs whitespace-nowrap ${isFixed ? "sticky left-0 z-10 bg-background" : ""}`}>
                            {String(row?.[c] ?? "")}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </CardContent>
      </Card>

      {p4pProductIdQuery.trim() && (
        <div className="grid grid-cols-1 md:grid-cols-2 min-[1700px]:grid-cols-4 gap-4 mt-6">
          <Card className="border border-border/60">
            <CardHeader className="pb-2"><CardTitle className="text-sm">产品详细信息</CardTitle></CardHeader>
            <CardContent>
              <div className="h-[280px] overflow-auto rounded-lg border border-border/50">
                <table className="min-w-full text-sm">
                  <thead className="sticky top-0 bg-muted/90"><tr className="border-b bg-muted/90"><th className="text-left py-2 px-3 text-xs">字段</th><th className="text-left py-2 px-3 text-xs">值</th></tr></thead>
                  <tbody>
                    {[
                      "平台内部产品分级",
                      "产品综合搜索排名",
                      "平台曝光标签",
                      "平台访客流量标签",
                      "平台点击效率标签",
                      "平台转化效果标签",
                    ].map((k) => (
                      <tr key={k} className="border-b last:border-0"><td className="py-2 px-3 text-xs">{k}</td><td className="py-2 px-3 text-xs">{String(detailInfoRows[0]?.[k] ?? "")}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card className="border border-border/60">
            <CardHeader className="pb-2"><CardTitle className="text-sm">关键词</CardTitle></CardHeader>
            <CardContent>
              <div className="h-[280px] overflow-auto rounded-lg border border-border/50">
                <table className="min-w-full text-sm">
                  <thead className="sticky top-0 bg-muted/90"><tr className="border-b bg-muted/90"><th className="text-left py-2 px-3 text-xs">关键词</th><th className="text-right py-2 px-3 text-xs">搜索曝光次数</th><th className="text-right py-2 px-3 text-xs">搜索点击次数</th><th className="text-right py-2 px-3 text-xs">询盘</th></tr></thead>
                  <tbody>
                    {keywordRows.length === 0 ? (
                      <tr><td colSpan={4} className="py-8 text-center text-xs text-muted-foreground">暂无关键词数据</td></tr>
                    ) : keywordRows.map((r: any, i: number) => (
                      <tr key={`kw-${i}`} className="border-b last:border-0"><td className="py-2 px-3 text-xs">{String(r?.["关键词"] ?? "")}</td><td className="py-2 px-3 text-xs text-right">{String(r?.["搜索曝光次数"] ?? "")}</td><td className="py-2 px-3 text-xs text-right">{String(r?.["搜索点击次数"] ?? "")}</td><td className="py-2 px-3 text-xs text-right">{String(r?.["询盘"] ?? "")}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card className="border border-border/60">
            <CardHeader className="pb-2"><CardTitle className="text-sm">访客地域</CardTitle></CardHeader>
            <CardContent>
              <div className="h-[280px] overflow-auto rounded-lg border border-border/50">
                <table className="min-w-full text-sm">
                  <thead className="sticky top-0 bg-muted/90"><tr className="border-b bg-muted/90"><th className="text-left py-2 px-3 text-xs">国家(中文)</th><th className="text-right py-2 px-3 text-xs">访客数(UV)</th></tr></thead>
                  <tbody>
                    {regionRows.length === 0 ? (
                      <tr><td colSpan={2} className="py-8 text-center text-xs text-muted-foreground">暂无访客地域数据</td></tr>
                    ) : regionRows.map((r: any, i: number) => (
                      <tr key={`rg-${i}`} className="border-b last:border-0"><td className="py-2 px-3 text-xs">{String(r?.["国家(中文)"] ?? "")}</td><td className="py-2 px-3 text-xs text-right">{String(r?.["访客数(UV)"] ?? "")}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card className="border border-border/60">
            <CardHeader className="pb-2"><CardTitle className="text-sm">流量来源</CardTitle></CardHeader>
            <CardContent>
              <div className="h-[280px] overflow-auto rounded-lg border border-border/50 p-2">
                {trafficSourceRows.length === 0 ? (
                  <div className="py-8 text-center text-xs text-muted-foreground">暂无流量来源数据</div>
                ) : (
                  <div className="space-y-1">
                    {trafficSourceRows.map((r, i) => (
                      <div key={`ts-${i}`} className="text-xs px-2 py-1 rounded border border-border/50">{r.item}</div>
                    ))}
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
