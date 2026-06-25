/**
 * DataAnalysis - 综合数据分析页面
 * 对应脚本: 下载数据的处理/main.py
 * 功能: 产品数据统计、趋势分析、新发链接监控、P4P数据统计
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { toast } from "sonner";
import { analysisApi, configApi, dataApi } from "@/lib/api";
import {
  BarChart3,
  ChevronRight,
  TrendingUp,
  TrendingDown,
  Minus,
  FileSpreadsheet,
  Play,
  ArrowUpDown,
  Eye,
  MousePointer,
  Users,
  MessageSquare,
  Star,
  Zap,
  Target,
  Activity,
} from "lucide-react";

// 对应 main.py 中的 TARGET_COLUMNS
const targetColumns = [
  "全店曝光次数", "全站推广曝光次数", "搜索曝光次数",
  "全店点击次数", "全站推广点击次数", "搜索点击次数",
  "访问人数", "收藏人数", "询盘人数", "TM咨询人数"
];

const statisticsSearchSheets = [
  "全店曝光次数", "全站推广曝光次数", "搜索曝光次数",
  "全店点击次数", "全站推广点击次数", "搜索点击次数",
  "访问人数", "询盘人数", "TM咨询人数",
  "自然曝光", "自然点击", "场景曝光", "场景点击",
];

// 模拟产品统计数据
const mockProducts = [
  {
    id: "P001", name: "蓝牙耳机 TWS",
    exposure: 12500, searchExposure: 8200, clicks: 320, searchClicks: 210,
    visitors: 280, favorites: 15, inquiries: 8, tmConsult: 3,
    trend: "up", isShowcase: true, isP4P: true,
  },
  {
    id: "P002", name: "无线充电器 15W",
    exposure: 9800, searchExposure: 6500, clicks: 250, searchClicks: 170,
    visitors: 220, favorites: 12, inquiries: 6, tmConsult: 2,
    trend: "up", isShowcase: true, isP4P: false,
  },
  {
    id: "P003", name: "Type-C数据线",
    exposure: 7600, searchExposure: 5100, clicks: 180, searchClicks: 120,
    visitors: 160, favorites: 8, inquiries: 3, tmConsult: 1,
    trend: "down", isShowcase: false, isP4P: true,
  },
  {
    id: "P004", name: "手机壳 防摔",
    exposure: 6200, searchExposure: 4300, clicks: 150, searchClicks: 95,
    visitors: 130, favorites: 6, inquiries: 2, tmConsult: 0,
    trend: "stable", isShowcase: false, isP4P: false,
  },
  {
    id: "P005", name: "LED灯带 RGB",
    exposure: 5400, searchExposure: 3800, clicks: 130, searchClicks: 85,
    visitors: 110, favorites: 5, inquiries: 4, tmConsult: 2,
    trend: "up", isShowcase: true, isP4P: true,
  },
];

// 对应 main.py 中的权重配置
const weightConfig = [
  { name: "自然曝光", weight: 0.25, base: 1000 },
  { name: "搜索曝光", weight: 0.20, base: 500 },
  { name: "综合询盘", weight: 0.15, base: 10 },
  { name: "自然询盘", weight: 0.20, base: 8 },
  { name: "收藏人数", weight: 0.10, base: 20 },
  { name: "访问人数", weight: 0.08, base: 100 },
];

// 对应 main.py 中的曝光阈值
const exposureThresholds = [
  { level: "大曝光", min: 1000, color: "bg-emerald-100 text-emerald-700" },
  { level: "有曝光", min: 100, color: "bg-blue-100 text-blue-700" },
  { level: "低曝光", min: 10, color: "bg-amber-100 text-amber-700" },
  { level: "未启动", min: 0, color: "bg-gray-100 text-gray-700" },
];

const DATA_ANALYSIS_BG = "https://d2xsxph8kpxj0f.cloudfront.net/310519663446710123/k5cTC97kfWVPorgBMMhfV3/data-analysis-bg-nxMiBxi4tyWLBxyNdfHrLB.webp";

export default function DataAnalysis() {
  const [location, setLocation] = useLocation();
  const [selectedProduct, setSelectedProduct] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [anomalyData, setAnomalyData] = useState<{ rows: any[] }>({ rows: [] });
  const [statisticsData, setStatisticsData] = useState<{ sheet: string; sheets: string[]; columns: string[]; rows: any[] }>({ sheet: "", sheets: [], columns: [], rows: [] });
  const [statisticsSheet, setStatisticsSheet] = useState("");
  const [statsSortKey, setStatsSortKey] = useState<string>("异动");
  const [statsSortDir, setStatsSortDir] = useState<"asc" | "desc">("desc");
  const [statisticsProductIdQuery, setStatisticsProductIdQuery] = useState("");
  const [anomalyProductIdQuery, setAnomalyProductIdQuery] = useState("");
  const [statisticsSearchRows, setStatisticsSearchRows] = useState<any[]>([]);
  const [statisticsSearchCols, setStatisticsSearchCols] = useState<string[]>([]);
  const [product360ExcelDir, setProduct360ExcelDir] = useState("");
  const [detailInfoRows, setDetailInfoRows] = useState<any[]>([]);
  const [keywordRows, setKeywordRows] = useState<any[]>([]);
  const [regionRows, setRegionRows] = useState<any[]>([]);
  const [trafficSourceRows, setTrafficSourceRows] = useState<Array<{ item: string }>>([]);

  const [p4pData, setP4pData] = useState<{ sheet: string; sheets: string[]; columns: string[]; rows: any[] }>({ sheet: "", sheets: [], columns: [], rows: [] });
  const [p4pSheet, setP4pSheet] = useState("");
  const [p4pSortKey, setP4pSortKey] = useState<string>("计划ID");
  const [p4pSortDir, setP4pSortDir] = useState<"asc" | "desc">("desc");
  const [p4pUseAbsDefaultSort, setP4pUseAbsDefaultSort] = useState(true);
  const [overviewStats, setOverviewStats] = useState({
    totalExposure: 0,
    totalClicks: 0,
    totalVisitors: 0,
    totalInquiry: 0,
    totalSearchClicks: 0,
  });
  const [newLinksOverviewStats, setNewLinksOverviewStats] = useState({
    totalExposure: 0,
    totalClicks: 0,
    totalVisitors: 0,
    totalInquiry: 0,
    totalSearchExposure: 0,
  });
  const [activeTab, setActiveTab] = useState("products");
  const [p4pOverviewStats, setP4pOverviewStats] = useState({
    exposure: 0,
    clicks: 0,
    opportunities: 0,
    inquiry: 0,
    tm: 0,
  });

  const [sourceDir, setSourceDir] = useState("");
  const [p4pSourceDir, setP4pSourceDir] = useState("");
  const [outputFile, setOutputFile] = useState("");
  const [p4pOutputFile, setP4pOutputFile] = useState("");
  const [newLinksPath, setNewLinksPath] = useState("");
  const [newOutputFile, setNewOutputFile] = useState("");
  const [diagnosisOutput, setDiagnosisOutput] = useState("");
  const [volatilityPath, setVolatilityPath] = useState("");
  const [singleAnalysisInputFile, setSingleAnalysisInputFile] = useState("");
  const [singleAnalysisOutputFile, setSingleAnalysisOutputFile] = useState("");
  const [singleAnalysisSummaryFile, setSingleAnalysisSummaryFile] = useState("");
  const [sortKey, setSortKey] = useState<string>("shopExposure");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [useAbsDefaultSort, setUseAbsDefaultSort] = useState(true);
  const [newLinksData, setNewLinksData] = useState<{ columns: string[]; rows: any[]; latest_col?: string }>({ columns: [], rows: [] });
  const [newLinksSheet, setNewLinksSheet] = useState("全店曝光次数");
  const [hoverRowIdx, setHoverRowIdx] = useState<number | null>(null);
  const [activeRowIdx, setActiveRowIdx] = useState<number | null>(null);
  const [newLinksSortKey, setNewLinksSortKey] = useState<string | null>(null);
  const [newLinksSortDir, setNewLinksSortDir] = useState<"asc" | "desc">("desc");
  const [weightRows, setWeightRows] = useState(weightConfig);

  const [diagnosisData, setDiagnosisData] = useState<{ columns: string[]; rows: any[] }>({ columns: [], rows: [] });
  const [diagnosisProductIdQuery, setDiagnosisProductIdQuery] = useState("");
  const [diagFilterNew, setDiagFilterNew] = useState("all");
  const [diagFilterExposure, setDiagFilterExposure] = useState("all");
  const [diagFilterHistory, setDiagFilterHistory] = useState("all");
  const [diagFilterPriority, setDiagFilterPriority] = useState("all");
  const [diagSortKey, setDiagSortKey] = useState<string>("权重评分");
  const [diagSortDir, setDiagSortDir] = useState<"asc" | "desc">("desc");

  const [pValueThreshold, setPValueThreshold] = useState(0.1);
  const [minDataPoints, setMinDataPoints] = useState(3);
  const [clickRateThreshold, setClickRateThreshold] = useState(0.02);
  const [inquiryRateThreshold, setInquiryRateThreshold] = useState(0.05);
  const [newProductWeeks, setNewProductWeeks] = useState(3);
  const [newProductFocusExposure, setNewProductFocusExposure] = useState(100);
  const diagnosisLeftRef = useRef<HTMLDivElement | null>(null);
  const diagnosisRightRef = useRef<HTMLDivElement | null>(null);

  const getTrendIcon = (trend: string) => {
    if (trend === "up") return <TrendingUp className="w-4 h-4 text-emerald-500" />;
    if (trend === "down") return <TrendingDown className="w-4 h-4 text-red-500" />;
    return <Minus className="w-4 h-4 text-gray-400" />;
  };

  const getExposureLevel = (exposure: number) => {
    for (const t of exposureThresholds) {
      if (exposure >= t.min) return t;
    }
    return exposureThresholds[exposureThresholds.length - 1];
  };

  const loadConfig = async () => {
    try {
      const sections = await configApi.getSections(["data_analysis", "data_download"]);
      const da = sections.data_analysis || {};
      const dd = sections.data_download || {};
      setSourceDir(da.source_dir || "");
      setP4pSourceDir(da.p4p_source_dir || "");
      setOutputFile(da.output_file || "");
      setP4pOutputFile(da.p4p_output_file || "");
      setNewLinksPath(da.new_links_file_path || "");
      setNewOutputFile(da.new_output_file || "");
      setDiagnosisOutput(da.diagnosis_output_file || "");
      setVolatilityPath(da.volatility_file_path || "");
      setSingleAnalysisInputFile(da.single_analysis_input_file || "");
      setSingleAnalysisOutputFile(da.single_analysis_output_file || "");
      setSingleAnalysisSummaryFile(da.single_analysis_summary_file || "");
      setProduct360ExcelDir(dd.product360_excel_result_dir || "");

      setPValueThreshold(Number(da.p_value_threshold ?? 0.1));
      setMinDataPoints(Number(da.min_data_points ?? 3));
      setClickRateThreshold(Number(da.click_rate_threshold ?? 0.02));
      setInquiryRateThreshold(Number(da.inquiry_rate_threshold ?? 0.05));
      setNewProductWeeks(Number(da.new_product_weeks ?? 3));
      setNewProductFocusExposure(Number(da.new_product_focus_exposure ?? 100));

      const wc = da.weight_config || {};
      const nb = da.normalize_base || {};
      setWeightRows((prev) => prev.map((w) => ({
        ...w,
        weight: Number(wc?.[w.name] ?? w.weight),
        base: Number(nb?.[w.name] ?? w.base),
      })));
    } catch {
      // ignore
    }
  };

  const saveConfig = async () => {
    try {
      const current = (await configApi.getSection("data_analysis")) || {};
      await configApi.updateSection("data_analysis", {
        ...current,
        source_dir: sourceDir,
        p4p_source_dir: p4pSourceDir,
        output_file: outputFile,
        p4p_output_file: p4pOutputFile,
        new_links_file_path: newLinksPath,
        new_output_file: newOutputFile,
        diagnosis_output_file: diagnosisOutput,
        volatility_file_path: volatilityPath,
        single_analysis_input_file: singleAnalysisInputFile,
        single_analysis_output_file: singleAnalysisOutputFile,
        single_analysis_summary_file: singleAnalysisSummaryFile,
        p_value_threshold: Number(pValueThreshold || 0.1),
        min_data_points: Number(minDataPoints || 3),
        click_rate_threshold: Number(clickRateThreshold || 0.02),
        inquiry_rate_threshold: Number(inquiryRateThreshold || 0.05),
        new_product_weeks: Number(newProductWeeks || 3),
        new_product_focus_exposure: Number(newProductFocusExposure || 100),
      });
      toast.success("分析配置已保存");
      refreshAnomaly();
    } catch (e: any) {
      toast.error(e?.message || "保存失败");
    }
  };

  const refreshStatus = async () => {
    try {
      const res = await analysisApi.getStatus("comprehensive");
      const payload = res?.data || res;
      const status = payload?.data || payload;
      setIsRunning(status?.status === "running" || status?.status === "stopping");
    } catch {
      // ignore
    }
  };

  const handleStartProductOptimizeSuggestion = async () => {
    try {
      const res = await analysisApi.getVolatilityAnomaly(volatilityPath || undefined);
      const payload = res?.data || res;
      const data = payload?.data || payload;
      const rows: any[] = Array.isArray(data?.rows) ? data.rows : [];
      const ids = rows
        .filter((row: any) => Number(String(row?.shopExposure ?? 0).replace(/,/g, "")) < 0)
        .map((row: any) => String(row?.productId ?? row?.产品ID ?? "").trim())
        .filter(Boolean);

      if (!ids.length) {
        toast.info("未找到全店曝光为负数的产品");
        return;
      }

      const query = new URLSearchParams({ source: "anomaly", ids: ids.join(",") }).toString();
      setLocation(`/title-optimize-analysis?${query}`);
      toast.success(`已将 ${ids.length} 个产品带入产品优化建议页`);
    } catch (e: any) {
      toast.error(e?.message || "筛选失败");
    }
  };

  const handleStartComprehensive = async () => {
    try {
      await analysisApi.start({ task_type: "comprehensive" });
      toast.success("综合分析已启动");
      refreshStatus();
      const poll = setInterval(async () => {
        try {
          const res = await analysisApi.getStatus("comprehensive");
          const payload = res?.data || res;
          const status = payload?.data || payload;
          const s = status?.status;
          if (s === "completed" || s === "failed" || s === "idle") {
            clearInterval(poll);
            await Promise.all([refreshStatistics(), refreshP4p(), refreshAnomaly(), refreshNewLinks(), refreshDiagnosis()]);
          }
        } catch {
          // ignore polling errors
        }
      }, 3000);
    } catch (e: any) {
      toast.error(e?.message || "启动失败");
    }
  };

  const refreshAnomaly = async () => {
    // 方案一：单品分析模式下不请求波动接口（避免 _unused_volatility 404）
    if ((volatilityPath || "").toLowerCase().includes("_unused_volatility.xlsx")) {
      setAnomalyData({ rows: [] });
      return;
    }

    try {
      const res = await analysisApi.getVolatilityAnomaly(volatilityPath || undefined);
      const payload = res?.data || res;
      const data = payload?.data || payload;
      setAnomalyData({
        rows: data?.rows || [],
      });
      setSortKey("shopExposure");
      setSortDir("desc");
      setUseAbsDefaultSort(true);
    } catch {
      // 保留已有异动数据
    }
  };

  const refreshStatistics = async (sheetName?: string) => {
    try {
      const res = await analysisApi.getStatisticsTable(outputFile || undefined, sheetName || statisticsSheet || undefined);
      const payload = res?.data || res;
      const data = payload?.data || payload;
      setStatisticsData({
        sheet: data?.sheet || "",
        sheets: data?.sheets || [],
        columns: data?.columns || [],
        rows: data?.rows || [],
      });
      if (!statisticsSheet && data?.sheet) {
        setStatisticsSheet(data.sheet);
      }
    } catch {
      // 保留已有统计数据
    }

    try {
      const [expRes, clickRes, visitRes, askRes, tmRes, searchClickRes] = await Promise.all([
        analysisApi.getStatisticsTable(outputFile || undefined, "全店曝光次数"),
        analysisApi.getStatisticsTable(outputFile || undefined, "全店点击次数"),
        analysisApi.getStatisticsTable(outputFile || undefined, "访问人数"),
        analysisApi.getStatisticsTable(outputFile || undefined, "询盘人数"),
        analysisApi.getStatisticsTable(outputFile || undefined, "TM咨询人数"),
        analysisApi.getStatisticsTable(outputFile || undefined, "搜索点击次数"),
      ]);

      const getLatestSum = (resp: any) => {
        const payloadX = resp?.data || resp;
        const d = payloadX?.data || payloadX;
        const cols: string[] = d?.columns || [];
        const rows: any[] = d?.rows || [];
        const weekCols = cols.filter((c) => /^\d{6}-\d{6}$/.test(String(c))).sort((a, b) => String(a).localeCompare(String(b)));
        const latestCol = weekCols.length ? weekCols[weekCols.length - 1] : null;
        if (!latestCol) return 0;
        return rows.reduce((sum, r) => {
          const v = Number(String(r?.[latestCol] ?? "0").replace(/,/g, ""));
          return sum + (Number.isFinite(v) ? v : 0);
        }, 0);
      };

      const totalExposure = getLatestSum(expRes);
      const totalClicks = getLatestSum(clickRes);
      const totalVisitors = getLatestSum(visitRes);
      const totalAsk = getLatestSum(askRes);
      const totalTm = getLatestSum(tmRes);
      const totalSearchClicks = getLatestSum(searchClickRes);

      setOverviewStats({
        totalExposure,
        totalClicks,
        totalVisitors,
        totalInquiry: totalAsk + totalTm,
        totalSearchClicks,
      });
    } catch {
      // 保留已有概览统计
    }

    // P4P概览（用于P4P tab顶部统计）
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

      setP4pOverviewStats({
        exposure: getLatestSumP4p(expRes),
        clicks: getLatestSumP4p(clickRes),
        opportunities: getLatestSumP4p(oppRes),
        inquiry: getLatestSumP4p(inqRes),
        tm: getLatestSumP4p(tmRes),
      });
    } catch {
      // 保留已有 P4P 概览
    }
  };

  const refreshP4p = async (sheetName?: string) => {
    try {
      const res = await analysisApi.getP4pTable(p4pOutputFile || undefined, sheetName || p4pSheet || undefined);
      const payload = res?.data || res;
      const data = payload?.data || payload;
      setP4pData({
        sheet: data?.sheet || "",
        sheets: data?.sheets || [],
        columns: data?.columns || [],
        rows: data?.rows || [],
      });

      const sheets: string[] = data?.sheets || [];
      const preferred = sheets.includes("曝光量") ? "曝光量" : "";
      if (!sheetName && !p4pSheet && preferred) {
        setP4pSheet(preferred);
      } else if (!p4pSheet && data?.sheet) {
        setP4pSheet(data.sheet);
      }
    } catch {
      // 保留已有 P4P 表格数据
    }
  };

  useEffect(() => {
    loadConfig();
    void refreshStatus();
  }, []);

  useEffect(() => {
    if (!isRunning) return;
    const t = setInterval(refreshStatus, 4000);
    return () => clearInterval(t);
  }, [isRunning]);

  useEffect(() => {
    try {
      const params = new URLSearchParams(window.location.search || "");
      const tab = (params.get("tab") || "").trim();
      if (["products", "p4p", "anomaly", "diagnosis", "weight", "thresholds", "config"].includes(tab)) {
        setActiveTab(tab);
      }
    } catch {
      // ignore
    }
  }, [location]);

  const refreshNewLinks = async () => {
    try {
      const res = await analysisApi.getNewLinksMonitor(newOutputFile || undefined, newLinksSheet || "全店曝光次数");
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

      const totalExposure = getLatestSum(expRes);
      const totalClicks = getLatestSum(clickRes);
      const totalVisitors = getLatestSum(visitRes);
      const totalAsk = getLatestSum(askRes);
      const totalTm = getLatestSum(tmRes);
      const totalSearchExposure = getLatestSum(searchExpRes);

      setNewLinksOverviewStats({
        totalExposure,
        totalClicks,
        totalVisitors,
        totalInquiry: totalAsk + totalTm,
        totalSearchExposure,
      });
    } catch {
      // 保留已有新发链接数据
    }
  };

  const refreshDiagnosis = async () => {
    try {
      const res = await analysisApi.getDiagnosisTable(diagnosisOutput || undefined);
      const payload = res?.data || res;
      const data = payload?.data || payload;
      setDiagnosisData({ columns: data?.columns || [], rows: data?.rows || [] });
    } catch {
      // 保留已有诊断数据
    }
  };

  useEffect(() => {
    if (volatilityPath) refreshAnomaly();
  }, [volatilityPath]);

  useEffect(() => {
    if (outputFile) {
      refreshStatistics(statisticsSheet || undefined);
    }
  }, [outputFile, statisticsSheet]);

  useEffect(() => {
    if (p4pOutputFile) {
      refreshP4p(p4pSheet || undefined);
    }
  }, [p4pOutputFile, p4pSheet]);

  useEffect(() => {
    if (newOutputFile) refreshNewLinks();
  }, [newOutputFile, newLinksSheet]);

  useEffect(() => {
    if (diagnosisOutput) refreshDiagnosis();
  }, [diagnosisOutput]);

  const handleSort = (key: string) => {
    setUseAbsDefaultSort(false);
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const sortedRows = [...(anomalyData.rows || [])].sort((a: any, b: any) => {
    const avRaw = Number(a?.[sortKey] ?? 0);
    const bvRaw = Number(b?.[sortKey] ?? 0);
    const useAbs = useAbsDefaultSort && sortKey === "shopExposure";
    const av = useAbs ? Math.abs(avRaw) : avRaw;
    const bv = useAbs ? Math.abs(bvRaw) : bvRaw;
    return sortDir === "asc" ? av - bv : bv - av;
  });

  const anomalyFilteredRows = sortedRows.filter((row: any) => {
    const q = anomalyProductIdQuery.trim();
    if (!q) return true;
    return String(row?.productId ?? "").includes(q);
  });

  const sortMark = (key: string) => (sortKey === key ? (sortDir === "asc" ? "↑" : "↓") : "");

  const toNumericLike = (v: any) => {
    if (v == null || v === "") return { num: 0, isNum: false };
    const s = String(v).replace(/,/g, "").replace(/%/g, "").trim();
    const n = Number(s);
    if (Number.isFinite(n)) return { num: n, isNum: true };
    return { num: 0, isNum: false };
  };

  const normalizePid = (v: any) => String(v ?? "").replace(/\.0+$/, "").trim();

  const statsRawCols = statisticsData.columns.length ? statisticsData.columns : ["产品ID"];
  const statsWeekCols = statsRawCols.filter((c) => /^\d{6}-\d{6}$/.test(String(c))).sort((a, b) => String(b).localeCompare(String(a)));
  const statsOtherCols = statsRawCols.filter((c) => !["产品ID", "异动", "涨跌"].includes(c) && !/^\d{6}-\d{6}$/.test(String(c)));
  const statisticsDisplayCols = [
    ...(statsRawCols.includes("产品ID") ? ["产品ID"] : []),
    ...(statsRawCols.includes("异动") ? ["异动"] : []),
    ...(statsRawCols.includes("涨跌") ? ["涨跌"] : []),
    ...statsWeekCols,
    ...statsOtherCols,
  ];

  const statsCanSort = (c: string) => c !== "产品ID";
  const statsSortMark = (c: string) => (statsSortKey === c ? (statsSortDir === "asc" ? "↑" : "↓") : "");
  const statsOnSort = (c: string) => {
    if (!statsCanSort(c)) return;
    if (statsSortKey === c) setStatsSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setStatsSortKey(c);
      setStatsSortDir("desc");
    }
  };

  const statisticsSortedRows = [...(statisticsData.rows || [])].sort((a: any, b: any) => {
    if (!statsSortKey || !statsCanSort(statsSortKey)) return 0;

    const avRaw = a?.[statsSortKey];
    const bvRaw = b?.[statsSortKey];
    const av = toNumericLike(avRaw);
    const bv = toNumericLike(bvRaw);

    if (av.isNum || bv.isNum) {
      return statsSortDir === "asc" ? av.num - bv.num : bv.num - av.num;
    }

    const as = String(avRaw ?? "");
    const bs = String(bvRaw ?? "");
    return statsSortDir === "asc" ? as.localeCompare(bs) : bs.localeCompare(as);
  });

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

  const p4pSortedRows = [...(p4pData.rows || [])].sort((a: any, b: any) => {
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

  const activeDetailQuery = (statisticsProductIdQuery || anomalyProductIdQuery || diagnosisProductIdQuery || "").trim();

  useEffect(() => {
    const run = async () => {
      const q = activeDetailQuery;
      if (!q || !outputFile) {
        setStatisticsSearchCols([]);
        setStatisticsSearchRows([]);
        setDetailInfoRows([]);
        setKeywordRows([]);
        setRegionRows([]);
        setTrafficSourceRows([]);
        return;
      }

      try {
        const rows: any[] = [];
        let mergedCols: string[] = ["指标", "产品ID"];

        for (const s of statisticsSearchSheets) {
          const res = await analysisApi.getStatisticsTable(outputFile || undefined, s);
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
        setStatisticsSearchCols(["指标", "产品ID", ...weekCols, ...otherCols]);
        setStatisticsSearchRows(rows);

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
        setStatisticsSearchCols(["指标", "产品ID"]);
        setStatisticsSearchRows(statisticsSearchSheets.map((name) => ({ 指标: name, 产品ID: q })));
      }
    };

    run();
  }, [activeDetailQuery, outputFile, product360ExcelDir]);


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

  const anomalySums = (() => {
    const rows = anomalyData.rows || [];
    const sum = (k: string) => rows.reduce((acc, r: any) => acc + (Number(String(r?.[k] ?? 0).replace(/,/g, "")) || 0), 0);
    return {
      shopExposure: sum("shopExposure"),
      p4pExposure: sum("p4pExposure"),
      searchExposure: sum("searchExposure"),
      naturalExposure: sum("naturalExposure"),
      sceneExposure: sum("sceneExposure"),
    };
  })();

  const topCards = (() => {
    if (activeTab === "p4p") {
      return [
        { label: "总曝光", value: p4pOverviewStats.exposure, icon: Eye, color: "text-blue-600", bg: "from-blue-50 to-white" },
        { label: "总点击", value: p4pOverviewStats.clicks, icon: MousePointer, color: "text-emerald-600", bg: "from-emerald-50 to-white" },
        { label: "全站商机", value: p4pOverviewStats.opportunities, icon: Users, color: "text-amber-600", bg: "from-amber-50 to-white" },
        { label: "询盘量", value: p4pOverviewStats.inquiry, icon: MessageSquare, color: "text-violet-600", bg: "from-violet-50 to-white" },
        { label: "全站商机-TM咨询量", value: p4pOverviewStats.tm, icon: Star, color: "text-rose-600", bg: "from-rose-50 to-white" },
      ];
    }
    if (activeTab === "anomaly") {
      return [
        { label: "总曝光", value: anomalySums.shopExposure, icon: Eye, color: "text-blue-600", bg: "from-blue-50 to-white" },
        { label: "全站推曝光", value: anomalySums.p4pExposure, icon: MousePointer, color: "text-emerald-600", bg: "from-emerald-50 to-white" },
        { label: "搜索曝光", value: anomalySums.searchExposure, icon: Users, color: "text-amber-600", bg: "from-amber-50 to-white" },
        { label: "自然曝光", value: anomalySums.naturalExposure, icon: MessageSquare, color: "text-violet-600", bg: "from-violet-50 to-white" },
        { label: "场景曝光", value: anomalySums.sceneExposure, icon: Star, color: "text-rose-600", bg: "from-rose-50 to-white" },
      ];
    }
    if (activeTab === "diagnosis") {
      const rows = diagnosisData.rows || [];
      const countByExposure = (v: string) => rows.filter((r: any) => String(r?.["曝光层级"] ?? "").includes(v)).length;
      const countByGroup = (v: string) => rows.filter((r: any) => String(r?.["新品分组"] ?? "").includes(v)).length;
      return [
        { label: "有大曝光", value: countByExposure("有大曝光"), icon: Eye, color: "text-blue-600", bg: "from-blue-50 to-white" },
        { label: "有曝光", value: countByExposure("有曝光"), icon: MousePointer, color: "text-emerald-600", bg: "from-emerald-50 to-white" },
        { label: "低曝光", value: countByExposure("低曝光"), icon: Users, color: "text-amber-600", bg: "from-amber-50 to-white" },
        { label: "新品分组-待观察", value: countByGroup("待观察"), icon: MessageSquare, color: "text-violet-600", bg: "from-violet-50 to-white" },
        { label: "新品分组-重点关注", value: countByGroup("重点关注"), icon: Star, color: "text-rose-600", bg: "from-rose-50 to-white" },
      ];
    }
    return [
      { label: "总曝光", value: overviewStats.totalExposure, icon: Eye, color: "text-blue-600", bg: "from-blue-50 to-white" },
      { label: "总点击", value: overviewStats.totalClicks, icon: MousePointer, color: "text-emerald-600", bg: "from-emerald-50 to-white" },
      { label: "总访客", value: overviewStats.totalVisitors, icon: Users, color: "text-amber-600", bg: "from-amber-50 to-white" },
      { label: "总询盘", value: overviewStats.totalInquiry, icon: MessageSquare, color: "text-violet-600", bg: "from-violet-50 to-white" },
      { label: "搜索点击", value: overviewStats.totalSearchClicks, icon: Star, color: "text-rose-600", bg: "from-rose-50 to-white" },
    ];
  })();

  return (
    <div className="p-8">
      <div className="mb-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>数据分析</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">综合分析</span>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">综合数据分析</h1>
            <p className="text-sm text-muted-foreground mt-1">
              产品数据统计、趋势回归分析、权重评分
            </p>
          </div>
          <div className="flex gap-3">
            <Button variant="outline" className="gap-2" onClick={() => toast.info("功能开发中")}>
              <FileSpreadsheet className="w-4 h-4" />
              导出报告
            </Button>
            <Button className="gap-2" onClick={handleStartProductOptimizeSuggestion} variant="outline">
              <Target className="w-4 h-4" />
              产品优化建议开始分析
            </Button>
            <Button className="gap-2" onClick={handleStartComprehensive} disabled={isRunning}>
              <Play className="w-4 h-4" />
              {isRunning ? "分析中..." : "执行分析"}
            </Button>
          </div>
        </div>
      </div>

      {/* Stats Overview */}
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

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="bg-muted/50">
          <TabsTrigger value="products" className="gap-2">
            <BarChart3 className="w-3.5 h-3.5" />
            产品数据
          </TabsTrigger>
          <TabsTrigger value="anomaly" className="gap-2">
            <Activity className="w-3.5 h-3.5" />
            异动明细
          </TabsTrigger>

          <TabsTrigger value="diagnosis" className="gap-2">
            <MessageSquare className="w-3.5 h-3.5" />
            诊断结果
          </TabsTrigger>
          <TabsTrigger value="weight" className="gap-2">
            <Target className="w-3.5 h-3.5" />
            权重配置
          </TabsTrigger>
          <TabsTrigger value="thresholds" className="gap-2">
            <Zap className="w-3.5 h-3.5" />
            阈值设置
          </TabsTrigger>
          <TabsTrigger value="config" className="gap-2">
            <ArrowUpDown className="w-3.5 h-3.5" />
            文件目录配置
          </TabsTrigger>
        </TabsList>

        {/* Products Data */}
        <TabsContent value="products" className="mt-6">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="text-base">产品数据（统计csss.xlsx）</CardTitle>
                <div className="flex items-center gap-2">
                  <Input
                    value={statisticsProductIdQuery}
                    onChange={(e) => setStatisticsProductIdQuery(e.target.value)}
                    placeholder="搜索产品ID（支持包含匹配）"
                    className="h-8 w-56 text-xs"
                  />
                  <select className="h-8 rounded border border-input bg-background px-2 text-xs" value={statisticsSheet} onChange={(e) => setStatisticsSheet(e.target.value)}>
                    {(statisticsData.sheets || []).map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                  <Button size="sm" variant="outline" onClick={() => refreshStatistics(statisticsSheet || undefined)}>刷新统计数据</Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className={`${statisticsProductIdQuery.trim() ? "h-[280px]" : "h-[560px]"} overflow-auto rounded-lg border border-border/50`}>
                {statisticsProductIdQuery.trim() ? (
                  <table className="min-w-max text-sm">
                    <thead className="sticky top-0 z-20 bg-muted/90 backdrop-blur">
                      <tr className="border-b bg-muted/90">
                        {(statisticsSearchCols.length ? statisticsSearchCols : ["指标", "产品ID"]).map((c) => (
                          <th key={c} className="text-left py-2 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap">
                            {c}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(statisticsSearchRows.length ? statisticsSearchRows : statisticsSearchSheets.map((name) => ({ 指标: name, 产品ID: statisticsProductIdQuery.trim() }))).map((row: any, idx: number) => (
                        <tr key={`stats-search-${idx}`} className="border-b last:border-0 hover:bg-accent/30 transition-colors">
                          {(statisticsSearchCols.length ? statisticsSearchCols : ["指标", "产品ID"]).map((c) => (
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
                      <tr className="border-b bg-muted/90">
                        {statisticsDisplayCols.map((c) => {
                          const isFixed = c === "产品ID";
                          return (
                            <th
                              key={c}
                              className={`text-left py-2 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap ${isFixed ? "sticky left-0 z-30 bg-muted/90" : ""} ${statsCanSort(c) ? "cursor-pointer select-none" : ""}`}
                              onClick={() => statsOnSort(c)}
                            >
                              {c}{statsSortMark(c) ? ` ${statsSortMark(c)}` : ""}
                            </th>
                          );
                        })}
                      </tr>
                    </thead>
                    <tbody>
                      {(statisticsData.rows || []).length === 0 ? (
                        <tr>
                          <td colSpan={Math.max(statisticsData.columns.length, 1)} className="py-10 text-center text-xs text-muted-foreground">暂无统计数据（请先执行综合分析）</td>
                        </tr>
                      ) : statisticsSortedRows.map((row: any, idx: number) => (
                        <tr key={`st-${idx}`} className="border-b last:border-0 hover:bg-accent/30 transition-colors">
                          {statisticsDisplayCols.map((c) => {
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

          {activeDetailQuery && (
            <div className="grid grid-cols-4 gap-4 mt-6">
              <Card className="border border-border/60">
                <CardHeader className="pb-2"><CardTitle className="text-sm">产品详细信息</CardTitle></CardHeader>
                <CardContent>
                  <div className="h-[320px] overflow-auto rounded-lg border border-border/50">
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



        </TabsContent>

        <TabsContent value="p4p" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">P4P分析已拆分为独立页面</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between rounded-lg border border-border/60 p-4">
                <div>
                  <div className="text-sm font-medium">请前往“数据分析 / P4P分析”查看</div>
                  <div className="text-xs text-muted-foreground mt-1">该模块已从综合分析中独立，方便单独查看和维护。</div>
                </div>
                <Button onClick={() => setLocation("/p4p-analysis")}>打开 P4P 分析页面</Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Anomaly Detail */}
        <TabsContent value="anomaly" className="mt-6">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="text-base">异动明细</CardTitle>
                <div className="flex items-center gap-2">
                  <Input
                    value={anomalyProductIdQuery}
                    onChange={(e) => setAnomalyProductIdQuery(e.target.value)}
                    placeholder="搜索产品ID（支持包含匹配）"
                    className="h-8 w-56 text-xs"
                  />
                  <Button size="sm" variant="outline" onClick={refreshAnomaly}>刷新异动数据</Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className={`${anomalyProductIdQuery.trim() ? "h-[300px]" : "h-[560px]"} overflow-y-auto rounded-lg border border-border/50`}>
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                    <tr className="border-b bg-muted/30">
                      <th className="text-left py-3 pl-3 pr-1 font-medium text-xs text-muted-foreground w-[150px]">产品ID</th>
                      <th className="text-right py-3 pl-1 pr-3 font-medium text-xs text-muted-foreground cursor-pointer select-none" onClick={() => handleSort("shopExposure")}>全店曝光 {sortMark("shopExposure")}</th>
                      <th className="text-right py-3 px-3 font-medium text-xs text-muted-foreground cursor-pointer select-none" onClick={() => handleSort("p4pExposure")}>全站推曝光 {sortMark("p4pExposure")}</th>
                      <th className="text-right py-3 px-3 font-medium text-xs text-muted-foreground cursor-pointer select-none" onClick={() => handleSort("searchExposure")}>搜索曝光 {sortMark("searchExposure")}</th>
                      <th className="text-right py-3 px-3 font-medium text-xs text-muted-foreground cursor-pointer select-none" onClick={() => handleSort("naturalExposure")}>自然曝光 {sortMark("naturalExposure")}</th>
                      <th className="text-right py-3 px-3 font-medium text-xs text-muted-foreground cursor-pointer select-none" onClick={() => handleSort("sceneExposure")}>场景曝光 {sortMark("sceneExposure")}</th>
                      <th className="text-right py-3 px-3 font-medium text-xs text-muted-foreground cursor-pointer select-none" onClick={() => handleSort("shopClicks")}>全店点击 {sortMark("shopClicks")}</th>
                      <th className="text-right py-3 px-3 font-medium text-xs text-muted-foreground cursor-pointer select-none" onClick={() => handleSort("p4pClicks")}>全站推点击 {sortMark("p4pClicks")}</th>
                      <th className="text-right py-3 px-3 font-medium text-xs text-muted-foreground cursor-pointer select-none" onClick={() => handleSort("searchClicks")}>搜索点击 {sortMark("searchClicks")}</th>
                      <th className="text-right py-3 px-3 font-medium text-xs text-muted-foreground cursor-pointer select-none" onClick={() => handleSort("naturalClicks")}>自然点击 {sortMark("naturalClicks")}</th>
                      <th className="text-right py-3 px-3 font-medium text-xs text-muted-foreground cursor-pointer select-none" onClick={() => handleSort("sceneClicks")}>场景点击 {sortMark("sceneClicks")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {anomalyFilteredRows.length === 0 ? (
                      <tr>
                        <td colSpan={11} className="py-10 text-center text-xs text-muted-foreground">暂无异动数据（请确认配置的流量波动.xlsx 存在且包含“异动”sheet，或搜索条件无匹配）</td>
                      </tr>
                    ) : anomalyFilteredRows.map((row: any, idx: number) => (
                      <tr key={`r-${idx}-${row.productId}`} className="border-b last:border-0 hover:bg-accent/30 transition-colors">
                        <td className="py-3 pl-3 pr-1 text-xs font-mono whitespace-nowrap">{row.productId}</td>
                        <td className="py-3 pl-1 pr-3 text-right text-xs">{Number(row.shopExposure || 0).toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-xs">{Number(row.p4pExposure || 0).toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-xs">{Number(row.searchExposure || 0).toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-xs">{Number(row.naturalExposure || 0).toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-xs">{Number(row.sceneExposure || 0).toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-xs">{Number(row.shopClicks || 0).toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-xs">{Number(row.p4pClicks || 0).toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-xs">{Number(row.searchClicks || 0).toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-xs">{Number(row.naturalClicks || 0).toLocaleString()}</td>
                        <td className="py-3 px-3 text-right text-xs">{Number(row.sceneClicks || 0).toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          {anomalyProductIdQuery.trim() && (
            <div className="grid grid-cols-4 gap-4 mt-6">
              <Card className="border border-border/60"><CardHeader className="pb-2"><CardTitle className="text-sm">产品详细信息</CardTitle></CardHeader><CardContent><div className="h-[320px] overflow-auto rounded-lg border border-border/50"><table className="min-w-full text-sm"><thead className="sticky top-0 bg-muted/90"><tr className="border-b bg-muted/90"><th className="text-left py-2 px-3 text-xs">字段</th><th className="text-left py-2 px-3 text-xs">值</th></tr></thead><tbody>{["平台内部产品分级","产品综合搜索排名","平台曝光标签","平台访客流量标签","平台点击效率标签","平台转化效果标签"].map((k)=>(<tr key={k} className="border-b last:border-0"><td className="py-2 px-3 text-xs">{k}</td><td className="py-2 px-3 text-xs">{String(detailInfoRows[0]?.[k] ?? "")}</td></tr>))}</tbody></table></div></CardContent></Card>
              <Card className="border border-border/60"><CardHeader className="pb-2"><CardTitle className="text-sm">关键词</CardTitle></CardHeader><CardContent><div className="h-[320px] overflow-auto rounded-lg border border-border/50"><table className="min-w-full text-sm"><thead className="sticky top-0 bg-muted/90"><tr className="border-b bg-muted/90"><th className="text-left py-2 px-3 text-xs">关键词</th><th className="text-right py-2 px-3 text-xs">搜索曝光次数</th><th className="text-right py-2 px-3 text-xs">搜索点击次数</th><th className="text-right py-2 px-3 text-xs">询盘</th></tr></thead><tbody>{keywordRows.length===0?(<tr><td colSpan={4} className="py-8 text-center text-xs text-muted-foreground">暂无关键词数据</td></tr>):keywordRows.map((r:any,i:number)=>(<tr key={`kw-a-${i}`} className="border-b last:border-0"><td className="py-2 px-3 text-xs">{String(r?.["关键词"] ?? "")}</td><td className="py-2 px-3 text-xs text-right">{String(r?.["搜索曝光次数"] ?? "")}</td><td className="py-2 px-3 text-xs text-right">{String(r?.["搜索点击次数"] ?? "")}</td><td className="py-2 px-3 text-xs text-right">{String(r?.["询盘"] ?? "")}</td></tr>))}</tbody></table></div></CardContent></Card>
              <Card className="border border-border/60"><CardHeader className="pb-2"><CardTitle className="text-sm">访客地域</CardTitle></CardHeader><CardContent><div className="h-[320px] overflow-auto rounded-lg border border-border/50"><table className="min-w-full text-sm"><thead className="sticky top-0 bg-muted/90"><tr className="border-b bg-muted/90"><th className="text-left py-2 px-3 text-xs">国家(中文)</th><th className="text-right py-2 px-3 text-xs">访客数(UV)</th></tr></thead><tbody>{regionRows.length===0?(<tr><td colSpan={2} className="py-8 text-center text-xs text-muted-foreground">暂无访客地域数据</td></tr>):regionRows.map((r:any,i:number)=>(<tr key={`rg-a-${i}`} className="border-b last:border-0"><td className="py-2 px-3 text-xs">{String(r?.["国家(中文)"] ?? "")}</td><td className="py-2 px-3 text-xs text-right">{String(r?.["访客数(UV)"] ?? "")}</td></tr>))}</tbody></table></div></CardContent></Card>
              <Card className="border border-border/60"><CardHeader className="pb-2"><CardTitle className="text-sm">流量来源</CardTitle></CardHeader><CardContent><div className="h-[320px] overflow-auto rounded-lg border border-border/50 p-2">{trafficSourceRows.length===0?(<div className="py-8 text-center text-xs text-muted-foreground">暂无流量来源数据</div>):(<div className="space-y-1">{trafficSourceRows.map((r,i)=>(<div key={`ts-a-${i}`} className="text-xs px-2 py-1 rounded border border-border/50">{r.item}</div>))}</div>)}</div></CardContent></Card>
            </div>
          )}
        </TabsContent>

        {/* Weight Config */}
        <TabsContent value="weight" className="mt-6">
          <div className="grid grid-cols-2 gap-6">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">权重评分配置</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {weightRows.map((w, idx) => (
                    <div key={w.name} className="flex items-center gap-4">
                      <Label className="w-24 text-sm">{w.name}</Label>
                      <div className="flex-1">
                        <div className="flex items-center gap-3">
                          <Input
                            type="number"
                            step={0.01}
                            min={0}
                            max={1}
                            value={w.weight}
                            onChange={(e) => {
                              const val = Number(e.target.value || 0);
                              setWeightRows((prev) => prev.map((r, i) => (i === idx ? { ...r, weight: Number.isFinite(val) ? val : 0 } : r)));
                            }}
                            className="w-24 text-sm"
                          />
                          <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                            <div
                              className="h-full bg-primary rounded-full transition-all"
                              style={{ width: `${Math.max(0, Math.min(1, w.weight)) * 100}%` }}
                            />
                          </div>
                          <span className="text-xs font-mono w-14 text-right">{(w.weight * 100).toFixed(1)}%</span>
                        </div>
                      </div>
                      <div className="text-xs text-muted-foreground w-20 text-right">基准: {w.base}</div>
                    </div>
                  ))}
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setWeightRows(weightConfig);
                      toast.success("权重配置已重置");
                    }}
                  >
                    重置权重
                  </Button>
                  <Button
                    size="sm"
                    onClick={async () => {
                      try {
                        const current = (await configApi.getSection("data_analysis")) || {};
                        const nextWeight: Record<string, number> = {};
                        const nextBase: Record<string, number> = {};
                        weightRows.forEach((w) => {
                          nextWeight[w.name] = Number(w.weight || 0);
                          nextBase[w.name] = Number(w.base || 0);
                        });
                        await configApi.updateSection("data_analysis", {
                          ...current,
                          weight_config: nextWeight,
                          normalize_base: nextBase,
                        });
                        toast.success("权重配置已保存");
                      } catch (e: any) {
                        toast.error(e?.message || "权重配置保存失败");
                      }
                    }}
                  >
                    保存权重
                  </Button>
                </div>
                <div className="mt-4 p-3 bg-blue-50 rounded-lg border border-blue-100">
                  <p className="text-[11px] text-blue-700">
                    权重评分 = 各维度(归一化值 x 权重) x 100 + 趋势加分(最高30分)，总分上限100分。
                    对应脚本中的 _calculate_weight_score() 函数。
                  </p>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-base">分析参数</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">P值阈值</Label>
                    <Input type="number" value={pValueThreshold} onChange={(e) => setPValueThreshold(Number(e.target.value))} step={0.01} className="text-sm" />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">最小数据点</Label>
                    <Input type="number" value={minDataPoints} onChange={(e) => setMinDataPoints(Number(e.target.value))} className="text-sm" />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">点击率阈值</Label>
                    <Input type="number" value={clickRateThreshold} onChange={(e) => setClickRateThreshold(Number(e.target.value))} step={0.01} className="text-sm" />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">询盘率阈值</Label>
                    <Input type="number" value={inquiryRateThreshold} onChange={(e) => setInquiryRateThreshold(Number(e.target.value))} step={0.01} className="text-sm" />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">新品连续周数</Label>
                    <Input type="number" value={newProductWeeks} onChange={(e) => setNewProductWeeks(Number(e.target.value))} className="text-sm" />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">新品关注曝光</Label>
                    <Input type="number" value={newProductFocusExposure} onChange={(e) => setNewProductFocusExposure(Number(e.target.value))} className="text-sm" />
                  </div>
                </div>
                <div className="pt-1">
                  <Button size="sm" onClick={saveConfig}>保存分析参数</Button>
                </div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="diagnosis" className="mt-6">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="text-base">产品诊断与优化建议</CardTitle>
                <Button size="sm" variant="outline" onClick={refreshDiagnosis}>刷新诊断表</Button>
              </div>
              <div className="grid grid-cols-5 gap-2 mt-3">
                <Input
                  value={diagnosisProductIdQuery}
                  onChange={(e) => setDiagnosisProductIdQuery(e.target.value)}
                  placeholder="搜索产品ID（支持包含匹配）"
                  className="h-8 text-xs"
                />

                <select className="h-8 rounded border border-input bg-background px-2 text-xs" value={diagFilterNew} onChange={(e) => setDiagFilterNew(e.target.value)}>
                  <option value="all">是否新品-全部</option>
                  <option value="是">是</option>
                  <option value="否">否</option>
                </select>

                <select className="h-8 rounded border border-input bg-background px-2 text-xs" value={diagFilterExposure} onChange={(e) => setDiagFilterExposure(e.target.value)}>
                  <option value="all">曝光层级-全部</option>
                  <option value="有大曝光">有大曝光</option>
                  <option value="有曝光">有曝光</option>
                  <option value="低曝光">低曝光</option>
                  <option value="未启动">未启动</option>
                </select>

                <select className="h-8 rounded border border-input bg-background px-2 text-xs" value={diagFilterHistory} onChange={(e) => setDiagFilterHistory(e.target.value)}>
                  <option value="all">历史最佳状态-全部</option>
                  <option value="优质品">优质品</option>
                  <option value="潜力品">潜力品</option>
                  <option value="问题品">问题品</option>
                </select>

                <select className="h-8 rounded border border-input bg-background px-2 text-xs" value={diagFilterPriority} onChange={(e) => setDiagFilterPriority(e.target.value)}>
                  <option value="all">行动优先级-全部</option>
                  <option value="高">高</option>
                  <option value="中">中</option>
                  <option value="低">低</option>
                </select>
              </div>
            </CardHeader>
            <CardContent>
              {(() => {
                const cols = diagnosisData.columns.length ? diagnosisData.columns : ["产品ID"];
                const fixed = ["产品ID"];
                const leftCols = cols.filter((c) => fixed.includes(c));
                const rightCols = cols.filter((c) => !fixed.includes(c));

                const sortable = new Set(["最近自然曝光", "最近搜索曝光", "最近自然询盘", "最近综合询盘", "权重评分"]);

                const query = diagnosisProductIdQuery.trim();
                const rows = (diagnosisData.rows || [])
                  .filter((r: any) => !query || String(r?.["产品ID"] ?? "").includes(query))
                  .filter((r: any) => diagFilterNew === "all" || String(r?.["是否新品"] ?? "") === diagFilterNew)
                  .filter((r: any) => diagFilterExposure === "all" || String(r?.["曝光层级"] ?? "").includes(diagFilterExposure))
                  .filter((r: any) => diagFilterHistory === "all" || String(r?.["历史最佳状态"] ?? "").includes(diagFilterHistory))
                  .filter((r: any) => diagFilterPriority === "all" || String(r?.["行动优先级"] ?? "").includes(diagFilterPriority))
                  .sort((a: any, b: any) => {
                    if (!sortable.has(diagSortKey)) return 0;
                    const av = Number(String(a?.[diagSortKey] ?? "").replace(/,/g, ""));
                    const bv = Number(String(b?.[diagSortKey] ?? "").replace(/,/g, ""));
                    const an = Number.isFinite(av) ? av : 0;
                    const bn = Number.isFinite(bv) ? bv : 0;
                    return diagSortDir === "asc" ? an - bn : bn - an;
                  });

                const mark = (k: string) => (diagSortKey === k ? (diagSortDir === "asc" ? "↑" : "↓") : "");
                const onSort = (k: string) => {
                  if (!sortable.has(k)) return;
                  if (diagSortKey === k) setDiagSortDir((d) => (d === "asc" ? "desc" : "asc"));
                  else {
                    setDiagSortKey(k);
                    setDiagSortDir("desc");
                  }
                };

                const stickyLeftMap: Record<string, string> = {
                  "产品ID": "left-0",
                };
                return (
                  <div className={`${diagnosisProductIdQuery.trim() ? "h-[300px]" : "h-[560px]"} overflow-auto rounded-lg border border-border/50`}>
                    <table className="min-w-max text-sm">
                      <thead className="sticky top-0 bg-muted/80 backdrop-blur z-20">
                        <tr className="h-9 border-b bg-muted/30">
                          {cols.map((c) => {
                            const isFixed = c === "产品ID";
                            const leftCls = stickyLeftMap[c] || "";
                            return (
                              <th
                                key={c}
                                className={`text-left py-2 px-3 font-medium text-xs text-muted-foreground whitespace-nowrap ${isFixed ? `sticky ${leftCls} z-30 bg-muted/90` : ""} ${sortable.has(c) ? "cursor-pointer select-none" : ""}`}
                                onClick={() => onSort(c)}
                              >
                                {c}{mark(c) ? ` ${mark(c)}` : ""}
                              </th>
                            );
                          })}
                        </tr>
                      </thead>
                      <tbody>
                        {rows.length === 0 ? (
                          <tr><td colSpan={Math.max(cols.length, 1)} className="py-10 text-center text-xs text-muted-foreground">暂无诊断数据</td></tr>
                        ) : rows.map((r: any, i: number) => (
                          <tr key={`dl-${i}`} className="h-8 border-b last:border-0 hover:bg-emerald-50/70">
                            {cols.map((c) => {
                              const isFixed = c === "产品ID";
                              const leftCls = stickyLeftMap[c] || "";
                              return (
                                <td key={c} className={`h-8 py-0 px-3 text-xs whitespace-nowrap align-middle ${isFixed ? `sticky ${leftCls} z-10 bg-background` : ""}`}>
                                  {String(r?.[c] ?? "")}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                );
              })()}
            </CardContent>
          </Card>

          {diagnosisProductIdQuery.trim() && (
            <div className="grid grid-cols-4 gap-4 mt-6">
              <Card className="border border-border/60"><CardHeader className="pb-2"><CardTitle className="text-sm">产品详细信息</CardTitle></CardHeader><CardContent><div className="h-[320px] overflow-auto rounded-lg border border-border/50"><table className="min-w-full text-sm"><thead className="sticky top-0 bg-muted/90"><tr className="border-b bg-muted/90"><th className="text-left py-2 px-3 text-xs">字段</th><th className="text-left py-2 px-3 text-xs">值</th></tr></thead><tbody>{["平台内部产品分级","产品综合搜索排名","平台曝光标签","平台访客流量标签","平台点击效率标签","平台转化效果标签"].map((k)=>(<tr key={k} className="border-b last:border-0"><td className="py-2 px-3 text-xs">{k}</td><td className="py-2 px-3 text-xs">{String(detailInfoRows[0]?.[k] ?? "")}</td></tr>))}</tbody></table></div></CardContent></Card>
              <Card className="border border-border/60"><CardHeader className="pb-2"><CardTitle className="text-sm">关键词</CardTitle></CardHeader><CardContent><div className="h-[320px] overflow-auto rounded-lg border border-border/50"><table className="min-w-full text-sm"><thead className="sticky top-0 bg-muted/90"><tr className="border-b bg-muted/90"><th className="text-left py-2 px-3 text-xs">关键词</th><th className="text-right py-2 px-3 text-xs">搜索曝光次数</th><th className="text-right py-2 px-3 text-xs">搜索点击次数</th><th className="text-right py-2 px-3 text-xs">询盘</th></tr></thead><tbody>{keywordRows.length===0?(<tr><td colSpan={4} className="py-8 text-center text-xs text-muted-foreground">暂无关键词数据</td></tr>):keywordRows.map((r:any,i:number)=>(<tr key={`kw-d-${i}`} className="border-b last:border-0"><td className="py-2 px-3 text-xs">{String(r?.["关键词"] ?? "")}</td><td className="py-2 px-3 text-xs text-right">{String(r?.["搜索曝光次数"] ?? "")}</td><td className="py-2 px-3 text-xs text-right">{String(r?.["搜索点击次数"] ?? "")}</td><td className="py-2 px-3 text-xs text-right">{String(r?.["询盘"] ?? "")}</td></tr>))}</tbody></table></div></CardContent></Card>
              <Card className="border border-border/60"><CardHeader className="pb-2"><CardTitle className="text-sm">访客地域</CardTitle></CardHeader><CardContent><div className="h-[320px] overflow-auto rounded-lg border border-border/50"><table className="min-w-full text-sm"><thead className="sticky top-0 bg-muted/90"><tr className="border-b bg-muted/90"><th className="text-left py-2 px-3 text-xs">国家(中文)</th><th className="text-right py-2 px-3 text-xs">访客数(UV)</th></tr></thead><tbody>{regionRows.length===0?(<tr><td colSpan={2} className="py-8 text-center text-xs text-muted-foreground">暂无访客地域数据</td></tr>):regionRows.map((r:any,i:number)=>(<tr key={`rg-d-${i}`} className="border-b last:border-0"><td className="py-2 px-3 text-xs">{String(r?.["国家(中文)"] ?? "")}</td><td className="py-2 px-3 text-xs text-right">{String(r?.["访客数(UV)"] ?? "")}</td></tr>))}</tbody></table></div></CardContent></Card>
              <Card className="border border-border/60"><CardHeader className="pb-2"><CardTitle className="text-sm">流量来源</CardTitle></CardHeader><CardContent><div className="h-[320px] overflow-auto rounded-lg border border-border/50 p-2">{trafficSourceRows.length===0?(<div className="py-8 text-center text-xs text-muted-foreground">暂无流量来源数据</div>):(<div className="space-y-1">{trafficSourceRows.map((r,i)=>(<div key={`ts-d-${i}`} className="text-xs px-2 py-1 rounded border border-border/50">{r.item}</div>))}</div>)}</div></CardContent></Card>
            </div>
          )}
        </TabsContent>

        {/* Thresholds */}
        <TabsContent value="thresholds" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">曝光等级阈值配置</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-6">
                <div>
                  <h3 className="text-sm font-medium mb-3">全店曝光阈值</h3>
                  <div className="space-y-3">
                    <div className="flex items-center gap-4">
                      <Badge className="w-20 justify-center bg-emerald-100 text-emerald-700 border-0">大曝光</Badge>
                      <span className="text-xs text-muted-foreground">≥</span>
                      <Input type="number" defaultValue={1000} className="w-32 text-sm" />
                    </div>
                    <div className="flex items-center gap-4">
                      <Badge className="w-20 justify-center bg-blue-100 text-blue-700 border-0">有曝光</Badge>
                      <span className="text-xs text-muted-foreground">≥</span>
                      <Input type="number" defaultValue={100} className="w-32 text-sm" />
                    </div>
                    <div className="flex items-center gap-4">
                      <Badge className="w-20 justify-center bg-amber-100 text-amber-700 border-0">低曝光</Badge>
                      <span className="text-xs text-muted-foreground">≥</span>
                      <Input type="number" defaultValue={10} className="w-32 text-sm" />
                    </div>
                  </div>
                </div>
                <div>
                  <h3 className="text-sm font-medium mb-3">搜索曝光阈值</h3>
                  <div className="space-y-3">
                    <div className="flex items-center gap-4">
                      <Badge className="w-20 justify-center bg-emerald-100 text-emerald-700 border-0">大曝光</Badge>
                      <span className="text-xs text-muted-foreground">≥</span>
                      <Input type="number" defaultValue={500} className="w-32 text-sm" />
                    </div>
                    <div className="flex items-center gap-4">
                      <Badge className="w-20 justify-center bg-blue-100 text-blue-700 border-0">有曝光</Badge>
                      <span className="text-xs text-muted-foreground">≥</span>
                      <Input type="number" defaultValue={100} className="w-32 text-sm" />
                    </div>
                    <div className="flex items-center gap-4">
                      <Badge className="w-20 justify-center bg-amber-100 text-amber-700 border-0">低曝光</Badge>
                      <span className="text-xs text-muted-foreground">≥</span>
                      <Input type="number" defaultValue={10} className="w-32 text-sm" />
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="newlinks" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">新发链接监控已拆分为独立页面</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between rounded-lg border border-border/60 p-4">
                <div>
                  <div className="text-sm font-medium">请前往“数据分析 / 新发链接监控”查看</div>
                  <div className="text-xs text-muted-foreground mt-1">该模块已从综合分析中独立，方便单独查看和维护。</div>
                </div>
                <Button onClick={() => setLocation("/new-links-analysis")}>打开 新发链接监控 页面</Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="config" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">文件目录配置</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">主数据目录（SOURCE_DIR）</Label>
                <Input value={sourceDir} onChange={(e) => setSourceDir(e.target.value)} placeholder="D:\\Users\\mikey\\Desktop\\产品分析\\产品数据分析" className="text-sm font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">P4P数据目录（P4P_SOURCE_DIR）</Label>
                <Input value={p4pSourceDir} onChange={(e) => setP4pSourceDir(e.target.value)} placeholder="D:\\Users\\mikey\\Desktop\\产品分析\\产品数据分析\\P4P数据" className="text-sm font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">统计输出文件（OUTPUT_FILE）</Label>
                <Input value={outputFile} onChange={(e) => setOutputFile(e.target.value)} placeholder="...\\统计csss.xlsx" className="text-sm font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">P4P输出文件（P4P_OUTPUT_FILE）</Label>
                <Input value={p4pOutputFile} onChange={(e) => setP4pOutputFile(e.target.value)} placeholder="...\\P4P数据统计.xlsx" className="text-sm font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">新发链接文件（NEW_LINKS_FILE）</Label>
                <Input value={newLinksPath} onChange={(e) => setNewLinksPath(e.target.value)} placeholder="...\\新发链接监控.xlsx" className="text-sm font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">新发链接输出（NEW_OUTPUT_FILE）</Label>
                <Input value={newOutputFile} onChange={(e) => setNewOutputFile(e.target.value)} placeholder="...\\新发链接数据监控.xlsx" className="text-sm font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">诊断输出（DIAGNOSIS_OUTPUT）</Label>
                <Input value={diagnosisOutput} onChange={(e) => setDiagnosisOutput(e.target.value)} placeholder="...\\产品诊断与优化建议.xlsx" className="text-sm font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">流量波动文件（VOLATILITY_OUTPUT，读取异动sheet）</Label>
                <Input value={volatilityPath} onChange={(e) => setVolatilityPath(e.target.value)} placeholder="...\\流量波动.xlsx" className="text-sm font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">单品分析输入目录（SINGLE_ANALYSIS_INPUT_FILE）</Label>
                <Input value={singleAnalysisInputFile} onChange={(e) => setSingleAnalysisInputFile(e.target.value)} placeholder="...\\单品分析输入目录" className="text-sm font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">单品分析输出目录（SINGLE_ANALYSIS_OUTPUT_FILE）</Label>
                <Input value={singleAnalysisOutputFile} onChange={(e) => setSingleAnalysisOutputFile(e.target.value)} placeholder="...\\单品分析输出目录" className="text-sm font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">单品统计汇总输出文件（SINGLE_ANALYSIS_SUMMARY_FILE）</Label>
                <Input value={singleAnalysisSummaryFile} onChange={(e) => setSingleAnalysisSummaryFile(e.target.value)} placeholder="...\\单品近90天统计.xlsx" className="text-sm font-mono" />
              </div>
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={saveConfig}>保存配置</Button>
                <Button size="sm" variant="ghost" onClick={loadConfig}>重载配置</Button>
                <Button size="sm" variant="ghost" onClick={refreshAnomaly}>读取异动</Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
