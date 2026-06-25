/**
 * ProductDiagnosis - 产品诊断页面
 * 对应脚本: 下载数据的处理/main.py 中的诊断逻辑
 * 功能: 产品健康度评估、问题诊断、优化建议
 */
import { useEffect, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "sonner";
import { analysisApi, configApi, dataApi } from "@/lib/api";
import {
  Stethoscope,
  ChevronRight,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  TrendingUp,
  TrendingDown,
  Eye,
  MousePointer,
  MessageSquare,
  Play,
  FileSpreadsheet,
  Target,
  Info,
  Activity,
} from "lucide-react";

// 当前系统真实诊断逻辑（与后端 analysis_service.py 对齐）
const diagnosisRules = [
  {
    id: "layering",
    name: "分层判定（核心）",
    desc: "先分层再评分：分层决定动作，评分决定同层优先级",
    conditions: [
      "待启动品：历史无任何周期满足 全店曝光 ≥ 100",
      "优质品：全店曝光 ≥ 100 且 点击率 ≥ 配置阈值 且 修正询盘率 ≥ 配置阈值",
      "问题品：全店曝光 ≥ 100 但未达到优质条件",
      "新品分组：重点关注 / 待观察 / 普通（按连续曝光与询盘信号）",
    ],
  },
  {
    id: "score",
    name: "权重评分（0~100）",
    desc: "所有产品都计算连续分；用于同层精细排序",
    conditions: [
      "基础分 = Σ[权重 × min(历史均值/基准, 1)] × 100",
      "权重：自然曝光0.30，搜索曝光0.25，综合询盘0.20，收藏0.15，访问0.10",
      "基准：自然曝光1000，搜索曝光500，综合询盘10，收藏20，访问100",
      "趋势加分：最近最多30周期，每项显著上升 +5，最多 +25，总分封顶100",
    ],
  },
  {
    id: "thresholds",
    name: "关键阈值",
    desc: "阈值支持配置，页面“阈值设置-分析参数”可调整",
    conditions: [
      "点击率阈值 click_rate_threshold（默认 2%）",
      "询盘率阈值 inquiry_rate_threshold（默认 5%）",
      "曝光层级：有大曝光(≥500) / 有曝光(≥100) / 低曝光(≥20) / 未启动",
      "判优质曝光门槛：全店曝光 ≥ 100",
    ],
  },
  {
    id: "action_and_sort",
    name: "动作映射与排序",
    desc: "动作标签用于执行，排序用于排队",
    conditions: [
      "建议动作：优质→推进，重点关注→培养，待观察→观察，问题品→优化，其余→放弃",
      "橱窗建议：优质/重点关注→推荐；问题品/待观察→优化后推；其余→不推荐",
      "排序层级：优质品 > 新品重点关注 > 新品待观察 > 问题品 > 待启动品",
      "同层排序：行动优先级(高>中>低) → 权重评分降序",
    ],
  },
];

type DiagnosisItem = {
  product: string;
  id: string;
  score: number;
  level: "healthy" | "attention" | "warning" | "critical";
  action: "推进" | "培养" | "观察" | "优化" | "放弃";
  status: string;
  group: string;
  chuangStatus: string;
  p4pStatus: string;
  detail: string;
  changeLog: string;
  issues: string[];
  suggestions: string[];
  metrics: { exposure: number; clickRate: string; inquiryRate: string; trend: "up" | "down" | "stable" };
};

type ProductDiagnosisProps = {
  mode?: "diagnosis" | "single";
  [key: string]: any;
};

export default function ProductDiagnosis({ mode = "diagnosis" }: ProductDiagnosisProps) {
  const [selectedProduct, setSelectedProduct] = useState(0);
  const [diagnosisOutput, setDiagnosisOutput] = useState("");
  const [diagnosisRows, setDiagnosisRows] = useState<DiagnosisItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionFilter, setActionFilter] = useState<"全部" | "推进" | "培养" | "观察" | "优化" | "放弃">("全部");
  const [singleFiles, setSingleFiles] = useState<Array<{ key: string; label: string; path: string; kind: "stats" | "diagnosis" | "summary" }>>([]);
  const [singleSelectedKey, setSingleSelectedKey] = useState<string>("");
  const [singleSheet, setSingleSheet] = useState<string>("");
  const [singlePreview, setSinglePreview] = useState<{ sheet?: string; sheets?: string[]; columns: string[]; rows: any[] }>({ columns: [], rows: [] });
  const [singleSortKey, setSingleSortKey] = useState<string>("");
  const [singleSortDir, setSingleSortDir] = useState<"asc" | "desc">("desc");
  const singleReqKeyRef = useRef<string>("");
  const singleCacheRef = useRef<Record<string, { sheet?: string; sheets?: string[]; columns: string[]; rows: any[] }>>({});

  const [kwClickableRows, setKwClickableRows] = useState<any[]>([]);
  const [kwNoClickRows, setKwNoClickRows] = useState<any[]>([]);
  const [regionRows, setRegionRows] = useState<any[]>([]);
  const [trafficSourceRows, setTrafficSourceRows] = useState<any[]>([]);
  const [product360Loading, setProduct360Loading] = useState(false);

  const getLevelInfo = (level: string) => {
    switch (level) {
      case "healthy":
        return { label: "健康", color: "bg-emerald-100 text-emerald-700 border-emerald-200", icon: CheckCircle2 };
      case "attention":
        return { label: "关注", color: "bg-blue-100 text-blue-700 border-blue-200", icon: Info };
      case "warning":
        return { label: "警告", color: "bg-amber-100 text-amber-700 border-amber-200", icon: AlertTriangle };
      case "critical":
        return { label: "危险", color: "bg-red-100 text-red-700 border-red-200", icon: XCircle };
      default:
        return { label: "未知", color: "bg-gray-100 text-gray-700 border-gray-200", icon: Info };
    }
  };

  const getScoreColor = (score: number) => {
    if (score >= 80) return "text-emerald-600";
    if (score >= 60) return "text-blue-600";
    if (score >= 40) return "text-amber-600";
    return "text-red-600";
  };

  const getScoreRingColor = (score: number) => {
    if (score >= 80) return "#10b981";
    if (score >= 60) return "#3b82f6";
    if (score >= 40) return "#f59e0b";
    return "#ef4444";
  };

  const loadDiagnosis = async () => {
    setLoading(true);
    try {
      const da = (await configApi.getSection("data_analysis")) || {};
      const out = mode === "single"
        ? (da?.single_analysis_output_file || "")
        : (da?.diagnosis_output_file || "");
      setDiagnosisOutput(out);

      if (mode === "single") {
        const statsPath = out ? `${out.replace(/\\+$/, "")}\\日数据统计.xlsx` : "";
        const diagPath = out ? `${out.replace(/\\+$/, "")}\\日数据产品诊断与优化建议.xlsx` : "";
        const summaryPath = (da?.single_analysis_summary_file || (out ? `${out.replace(/\\+$/, "")}\\单品近90天统计.xlsx` : "")) as string;
        const files = [
          { key: "stats", label: "日数据统计.xlsx", path: statsPath, kind: "stats" as const },
          { key: "diag", label: "日数据产品诊断与优化建议.xlsx", path: diagPath, kind: "diagnosis" as const },
          { key: "summary", label: "单品近90天统计.xlsx", path: summaryPath, kind: "summary" as const },
        ].filter((f) => !!f.path);
        setSingleFiles(files);
        singleReqKeyRef.current = "";
        singleCacheRef.current = {};
        setSingleSelectedKey((prev) => (prev && files.some((f) => f.key === prev) ? prev : (files[0]?.key || "")));
        setDiagnosisRows([]);
        setSingleSheet("");
        setSingleSortKey("");
        setSingleSortDir("desc");
        setKwClickableRows([]);
        setKwNoClickRows([]);
        setRegionRows([]);
        setTrafficSourceRows([]);
        setLoading(false);
        return;
      }

      const res = await analysisApi.getDiagnosisTable(out || undefined);
      const payload = res?.data || res;
      const data = payload?.data || payload;
      const rows = (data?.rows || []) as any[];

      const mapped: DiagnosisItem[] = rows.map((r) => {
        const score = Number(r?.["权重评分"] ?? 0);
        const priority = String(r?.["行动优先级"] ?? "");
        const level: DiagnosisItem["level"] = score >= 80 ? "healthy" : score >= 60 ? "attention" : score >= 40 ? "warning" : "critical";

        const detail = String(r?.["诊断详情"] ?? "").trim();
        const issueText = detail ? detail.split("；")[0] : "";
        const chuang = String(r?.["橱窗建议"] ?? "").trim();
        const p4p = String(r?.["P4P建议"] ?? "").trim();

        const actionRaw = String(r?.["建议动作"] ?? "").trim();
        const action = (["推进", "培养", "观察", "优化", "放弃"].includes(actionRaw) ? actionRaw : "观察") as DiagnosisItem["action"];

        const detailClickMatch = detail.match(/点击率\s*([0-9]+(?:\.[0-9]+)?%)/);
        const clickRate = String(
          r?.["最近点击率"] ?? r?.["点击率"] ?? (detailClickMatch ? detailClickMatch[1] : "—")
        );

        return {
          product: String(r?.["产品ID"] ?? "未命名产品"),
          id: String(r?.["产品ID"] ?? ""),
          score: Number.isFinite(score) ? score : 0,
          level,
          action,
          status: String(r?.["历史最佳状态"] ?? ""),
          group: String(r?.["新品分组"] ?? ""),
          chuangStatus: String(r?.["橱窗状态"] ?? "未知"),
          p4pStatus: String(r?.["P4P状态"] ?? "未知"),
          detail,
          changeLog: String(r?.["操作变更记录"] ?? "").trim(),
          issues: issueText ? [issueText] : [],
          suggestions: [chuang, p4p].filter(Boolean),
          metrics: {
            exposure: Number(r?.["最近自然曝光"] ?? 0) + Number(r?.["最近搜索曝光"] ?? 0),
            clickRate,
            inquiryRate: String(r?.["修正询盘率"] ?? "0%"),
            trend: priority === "高" ? "up" : priority === "低" ? "down" : "stable",
          },
        };
      });

      setDiagnosisRows(mapped);
      setSelectedProduct(0);
    } catch (e: any) {
      toast.error(e?.message || "读取诊断结果失败");
      // 保留已有诊断行，避免二次进入或轮询失败时表格被清空
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDiagnosis();
  }, []);

  useEffect(() => {
    if (mode !== "single") return;
    const target = singleFiles.find((f) => f.key === singleSelectedKey);
    if (!target?.path) {
      setSinglePreview({ columns: [], rows: [] });
      return;
    }

    const reqKey = `${target.key}|${target.path}|${target.kind}|${target.kind === "stats" ? (singleSheet || "") : ""}`;
    if (singleReqKeyRef.current === reqKey) return;
    singleReqKeyRef.current = reqKey;

    const cached = singleCacheRef.current[reqKey];
    if (cached) {
      setSinglePreview(cached);
      return;
    }

    const run = async () => {
      try {
        if (target.kind === "stats") {
          const res = await analysisApi.getStatisticsTable(target.path, singleSheet || undefined);
          const payload = res?.data || res;
          const data = payload?.data || payload;
          const next = {
            sheet: data?.sheet,
            sheets: data?.sheets || [],
            columns: data?.columns || [],
            rows: data?.rows || [],
          };
          singleCacheRef.current[reqKey] = next;
          setSinglePreview(next);

          const currentSheet = String(data?.sheet || "");
          if (!singleSheet && currentSheet) {
            setSingleSheet(currentSheet);
          }

          const cols: string[] = data?.columns || [];
          const isDateCol = (c: string) => /^\d{6}(?:-\d{6})?$/.test(String(c));
          const latestDateCol = cols.filter(isDateCol).sort((a, b) => String(b).localeCompare(String(a)))[0] || "";
          if (!singleSortKey && latestDateCol) {
            setSingleSortKey(latestDateCol);
            setSingleSortDir("desc");
          }
        } else if (target.kind === "summary") {
          const res = await analysisApi.getDiagnosisTable(target.path);
          const payload = res?.data || res;
          const data = payload?.data || payload;
          const next = { columns: data?.columns || [], rows: data?.rows || [] };
          singleCacheRef.current[reqKey] = next;
          setSinglePreview(next);
          if (!singleSortKey) {
            setSingleSortKey((data?.columns || []).includes("90天提交订单数") ? "90天提交订单数" : "");
            setSingleSortDir("desc");
          }
        } else {
          const res = await analysisApi.getDiagnosisTable(target.path);
          const payload = res?.data || res;
          const data = payload?.data || payload;
          const next = { columns: data?.columns || [], rows: data?.rows || [] };
          singleCacheRef.current[reqKey] = next;
          setSinglePreview(next);
          if (!singleSortKey) {
            setSingleSortDir("desc");
          }
        }
      } catch {
        setSinglePreview({ columns: [], rows: [] });
      }
    };

    run();
  }, [mode, singleFiles, singleSelectedKey, singleSheet, singleSortKey]);

  const handleStartAnalysis = async () => {
    try {
      setLoading(true);
      const da = (await configApi.getSection("data_analysis")) || {};
      const sourceFile = mode === "single" ? (da?.single_analysis_input_file || undefined) : undefined;

      await analysisApi.start({ task_type: mode === "single" ? "single_analysis" : "comprehensive", ...(sourceFile ? { source_file: sourceFile } : {}) });
      toast.success(mode === "single" ? "单品分析任务已启动" : "分析任务已启动");

      const poll = setInterval(async () => {
        try {
          const res = await analysisApi.getStatus(mode === "single" ? "single_analysis" : "comprehensive");
          const payload = res?.data || res;
          const st = payload?.data || payload;
          const s = st?.status;
          if (s === "completed" || s === "failed" || s === "idle") {
            clearInterval(poll);
            await loadDiagnosis();
            setLoading(false);
            if (s === "completed") toast.success("分析完成，诊断结果已更新");
            if (s === "failed") toast.error("分析失败，请查看日志");
          }
        } catch {
          // ignore polling errors
        }
      }, 3000);
    } catch (e: any) {
      setLoading(false);
      toast.error(e?.message || "启动分析失败");
    }
  };

  const actionCount = {
    推进: diagnosisRows.filter((r) => r.action === "推进").length,
    培养: diagnosisRows.filter((r) => r.action === "培养").length,
    观察: diagnosisRows.filter((r) => r.action === "观察").length,
    优化: diagnosisRows.filter((r) => r.action === "优化").length,
    放弃: diagnosisRows.filter((r) => r.action === "放弃").length,
  };

  const filteredRows = actionFilter === "全部" ? diagnosisRows : diagnosisRows.filter((r) => r.action === actionFilter);

  useEffect(() => {
    setSelectedProduct(0);
  }, [actionFilter, diagnosisRows.length]);

  const selected = filteredRows[selectedProduct] || {
    product: "暂无数据",
    id: "",
    score: 0,
    level: "critical" as const,
    action: "观察" as const,
    status: "",
    group: "",
    chuangStatus: "—",
    p4pStatus: "—",
    detail: "",
    changeLog: "",
    issues: [],
    suggestions: [],
    metrics: { exposure: 0, clickRate: "—", inquiryRate: "—", trend: "stable" as const },
  };
  const levelInfo = getLevelInfo(selected.level);

  const actionBgMap: Record<DiagnosisItem["action"], string> = {
    推进: "bg-emerald-50 border-emerald-100 text-emerald-800",
    培养: "bg-blue-50 border-blue-100 text-blue-800",
    观察: "bg-slate-50 border-slate-100 text-slate-800",
    优化: "bg-amber-50 border-amber-100 text-amber-800",
    放弃: "bg-rose-50 border-rose-100 text-rose-800",
  };

  const statusHintMap: Record<string, string> = {
    "优质品": "表现稳定且转化达标，建议优先推进并持续放量。",
    "问题品": "有曝光但转化偏弱，建议先优化主图/标题/属性/价格后再加推。",
    "待启动品": "当前曝光或转化基础不足，建议暂缓投入或作为下架候选。",
    "潜力品": "具备增长潜力，建议持续优化并小步放量验证。",
  };

  const groupHintMap: Record<string, string> = {
    "重点关注": "新品中有明显增长信号，建议重点培养。",
    "待观察": "新品已有启动迹象，建议小流量持续观察。",
    "普通": "新品暂无明显信号，先维持基础优化。",
  };

  const previewColumns = (() => {
    if (singlePreview.columns.length === 0) return [] as string[];
    const isDateCol = (c: string) => /^\d{6}(?:-\d{6})?$/.test(String(c));
    const fixed = singlePreview.columns.filter((c) => !isDateCol(c));
    const dates = singlePreview.columns
      .filter(isDateCol)
      .sort((a, b) => String(b).localeCompare(String(a)));
    return [...fixed, ...dates];
  })();

  const sortedSingleRows = (() => {
    const rows = [...(singlePreview.rows || [])];
    if (!singleSortKey) return rows;

    const toNum = (v: any) => {
      const n = Number(String(v ?? "").replace(/,/g, "").trim());
      return Number.isFinite(n) ? n : 0;
    };

    const absByDefault = /^\d{6}(?:-\d{6})?$/.test(singleSortKey);

    rows.sort((a, b) => {
      const av = toNum(a?.[singleSortKey]);
      const bv = toNum(b?.[singleSortKey]);
      const left = absByDefault ? Math.abs(av) : av;
      const right = absByDefault ? Math.abs(bv) : bv;
      return singleSortDir === "asc" ? left - right : right - left;
    });

    return rows;
  })();

  const handleSingleSort = (col: string) => {
    if (col === "产品ID") return;
    if (singleSortKey === col) {
      setSingleSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSingleSortKey(col);
      setSingleSortDir("desc");
    }
  };

  useEffect(() => {
    if (mode === "single") return;

    const normalizePid = (v: any) => {
      const s = String(v ?? "").trim();
      if (!s) return "";
      const m = s.match(/\d{9,}/);
      if (m) return m[0];
      return s.replace(/\.0+$/, "").replace(/[^\d]/g, "").trim();
    };

    const pid = normalizePid(selected?.id || "");
    if (!pid) {
      setKwClickableRows([]);
      setKwNoClickRows([]);
      setRegionRows([]);
      setTrafficSourceRows([]);
      return;
    }

    const toNum = (v: any) => {
      const n = Number(String(v ?? "").replace(/,/g, "").trim());
      return Number.isFinite(n) ? n : 0;
    };

    const run = async () => {
      try {
        setProduct360Loading(true);
        const dd = (await configApi.getSection("data_download")) || {};
        const excelResultPath = dd.product360_excel_result_dir
          || dd.product360_output_dir
          || "";

        const [kwRes, regionRes, sourceRes] = await Promise.all([
          dataApi.getProduct360Table(excelResultPath, "关键词"),
          dataApi.getProduct360Table(excelResultPath, "访客地域"),
          dataApi.getProduct360Table(excelResultPath, "流量来源"),
        ]);

        const kwData = (kwRes?.data || kwRes)?.data || (kwRes?.data || kwRes) || {};
        const regionData = (regionRes?.data || regionRes)?.data || (regionRes?.data || regionRes) || {};
        const sourceData = (sourceRes?.data || sourceRes)?.data || (sourceRes?.data || sourceRes) || {};

        const kwCols: string[] = kwData?.columns || [];
        const regionCols: string[] = regionData?.columns || [];
        const sourceCols: string[] = sourceData?.columns || [];

        const getByIndex = (row: any, cols: string[], idx: number) => {
          const k = cols[idx];
          return k ? row?.[k] : undefined;
        };

        // 兼容列名乱码：优先标准列名，回退到固定列序（按 columns 映射，避免 Object.values 顺序不稳定）
        const kwRowsAll = (kwData?.rows || []).filter((r: any) => {
          const pidVal = r?.["产品ID"] ?? getByIndex(r, kwCols, 0);
          return normalizePid(pidVal) === pid;
        });
        const kwFiltered = kwRowsAll.filter((r: any) => {
          const exposure = toNum(r?.["搜索曝光次数"] ?? getByIndex(r, kwCols, 2));
          const clicks = toNum(r?.["搜索点击次数"] ?? getByIndex(r, kwCols, 3));
          return exposure > 10 || (exposure < 10 && clicks >= 3);
        });
        const kwLeft = kwFiltered
          .filter((r: any) => toNum(r?.["搜索点击次数"] ?? getByIndex(r, kwCols, 3)) !== 0)
          .map((r: any) => ({
            关键词: r?.["关键词"] ?? getByIndex(r, kwCols, 1) ?? "",
            曝光: toNum(r?.["搜索曝光次数"] ?? getByIndex(r, kwCols, 2)),
            点击: toNum(r?.["搜索点击次数"] ?? getByIndex(r, kwCols, 3)),
            商详访客: toNum(r?.["商品详情页访问人数"] ?? getByIndex(r, kwCols, 7)),
            询盘: toNum(r?.["店内询盘人数"] ?? getByIndex(r, kwCols, 8)) + toNum(r?.["店内 TM 咨询人数"] ?? getByIndex(r, kwCols, 9)),
          }));
        const kwRight = kwFiltered
          .filter((r: any) => toNum(r?.["搜索点击次数"] ?? getByIndex(r, kwCols, 3)) === 0)
          .map((r: any) => ({
            关键词: r?.["关键词"] ?? getByIndex(r, kwCols, 1) ?? "",
            曝光: toNum(r?.["搜索曝光次数"] ?? getByIndex(r, kwCols, 2)),
            点击: toNum(r?.["搜索点击次数"] ?? getByIndex(r, kwCols, 3)),
            商详访客: toNum(r?.["商品详情页访问人数"] ?? getByIndex(r, kwCols, 7)),
            询盘: toNum(r?.["店内询盘人数"] ?? getByIndex(r, kwCols, 8)) + toNum(r?.["店内 TM 咨询人数"] ?? getByIndex(r, kwCols, 9)),
          }));

        const regionRaw = regionData?.rows || [];
        const regionHasPid = regionRaw.some((r: any) => String(r?.["产品ID"] ?? getByIndex(r, regionCols, 0) ?? "").trim().length >= 9);
        const regionRowsFiltered = regionRaw
          .filter((r: any) => {
            if (!regionHasPid) return true;
            const rid = normalizePid(r?.["产品ID"] ?? getByIndex(r, regionCols, 0));
            return rid === pid;
          })
          .map((r: any) => ({
            国家: r?.["国家(中文)"] ?? getByIndex(r, regionCols, 2) ?? getByIndex(r, regionCols, 0) ?? "",
            访客数: toNum(r?.["访客数(UV)"] ?? r?.["访客量"] ?? getByIndex(r, regionCols, 3) ?? getByIndex(r, regionCols, 1)),
          }))
          .filter((r: any) => r.国家)
          .sort((a: any, b: any) => b.访客数 - a.访客数);

        const sourceRowsAll = sourceData?.rows || [];
        const sourceRowsForPid = sourceRowsAll.filter((r: any) => {
          const pidVal = r?.["产品ID"] ?? getByIndex(r, sourceCols, 0);
          return normalizePid(pidVal) === pid;
        });
        const latestDate = sourceRowsForPid
          .map((r: any) => String(r?.["日期"] ?? getByIndex(r, sourceCols, 1) ?? "").trim())
          .filter(Boolean)
          .sort((a: string, b: string) => b.localeCompare(a))[0] || "";
        const sourceRowsFiltered = sourceRowsForPid
          .filter((r: any) => String(r?.["日期"] ?? getByIndex(r, sourceCols, 1) ?? "").trim() === latestDate)
          .map((r: any) => ({
            流量渠道类型: r?.["流量渠道类型"] ?? getByIndex(r, sourceCols, 2) ?? "",
            店铺访问人数: toNum(r?.["店铺访问人数"] ?? getByIndex(r, sourceCols, 3)),
            询盘人数: toNum(r?.["询盘人数"] ?? getByIndex(r, sourceCols, 4)),
            TM咨询人数: toNum(r?.["TM咨询人数"] ?? getByIndex(r, sourceCols, 5)),
          }))
          .filter((r: any) => r.流量渠道类型);

        // 防止切换产品时旧请求覆盖新请求
        if (normalizePid(selected?.id || "") !== pid) return;

        setKwClickableRows(kwLeft);
        setKwNoClickRows(kwRight);
        setRegionRows(regionRowsFiltered);
        setTrafficSourceRows(sourceRowsFiltered);
      } catch {
        setKwClickableRows([]);
        setKwNoClickRows([]);
        setRegionRows([]);
        setTrafficSourceRows([]);
      } finally {
        setProduct360Loading(false);
      }
    };

    run();
  }, [mode, selected?.id]);

  return (
    <div className="p-8">
      <div className="mb-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>数据分析</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">产品诊断</span>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">{mode === "single" ? "单品分析" : "产品诊断"}</h1>
            <p className="text-sm text-muted-foreground mt-1">
              {mode === "single" ? "基于单品每日数据进行统计" : "基于多维指标的产品健康度评估、问题诊断与优化建议"}
            </p>
          </div>
          <div className="flex gap-3">
            <Button variant="outline" className="gap-2" onClick={() => toast.info("功能开发中")}>
              <FileSpreadsheet className="w-4 h-4" />
              导出报告
            </Button>
            <Button className="gap-2" onClick={mode === "single" ? handleStartAnalysis : loadDiagnosis} disabled={loading}>
              <Play className="w-4 h-4" />
              {loading ? "进行中..." : (mode === "single" ? "开始分析" : "刷新诊断")}
            </Button>
          </div>
        </div>
      </div>

      {mode !== "single" && (
        <>
          <div className="mb-3 flex items-center gap-2">
            <span className="text-xs text-muted-foreground">动作筛选</span>
            {(["全部", "推进", "培养", "观察", "优化", "放弃"] as const).map((a) => (
              <Button
                key={a}
                size="sm"
                variant={actionFilter === a ? "default" : "outline"}
                className="h-7 px-2 text-xs"
                onClick={() => setActionFilter(a)}
              >
                {a}
              </Button>
            ))}
          </div>

          <div className="mb-4 grid grid-cols-5 gap-3">
            {[
              { k: "推进", v: actionCount.推进, cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
              { k: "培养", v: actionCount.培养, cls: "bg-blue-50 text-blue-700 border-blue-200" },
              { k: "观察", v: actionCount.观察, cls: "bg-slate-50 text-slate-700 border-slate-200" },
              { k: "优化", v: actionCount.优化, cls: "bg-amber-50 text-amber-700 border-amber-200" },
              { k: "放弃", v: actionCount.放弃, cls: "bg-rose-50 text-rose-700 border-rose-200" },
            ].map((x) => (
              <div key={x.k} className={`rounded-lg border px-3 py-2 ${x.cls}`}>
                <div className="text-xs">{x.k}</div>
                <div className="text-xl font-bold leading-tight">{x.v}</div>
              </div>
            ))}
          </div>
        </>
      )}


      {mode === "single" ? (
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">单品分析输出文件</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {singleFiles.length === 0 ? (
                  <div className="text-xs text-muted-foreground">暂无输出文件，请先点击“开始分析”</div>
                ) : singleFiles.map((f) => (
                  <Button
                    key={f.key}
                    size="sm"
                    variant={singleSelectedKey === f.key ? "default" : "outline"}
                    onClick={() => {
                      setSingleSelectedKey(f.key);
                      setSingleSortKey("");
                      setSingleSortDir("desc");
                    }}
                  >
                    {f.label}
                  </Button>
                ))}
              </div>
              {singleFiles.length > 0 && (
                <div className="text-xs text-muted-foreground mt-2 break-all">
                  当前文件：{singleFiles.find((f) => f.key === singleSelectedKey)?.path || "—"}
                </div>
              )}

              {singleFiles.find((f) => f.key === singleSelectedKey)?.kind === "stats" && (singlePreview.sheets || []).length > 0 && (
                <div className="mt-3 flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">Sheet</span>
                  <select
                    className="h-8 rounded border border-input bg-background px-2 text-xs"
                    value={singleSheet || String(singlePreview.sheet || "")}
                    onChange={(e) => setSingleSheet(e.target.value)}
                  >
                    {(singlePreview.sheets || []).map((s) => (
                      <option key={s} value={s}>{s}</option>
                    ))}
                  </select>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">文件内容预览</CardTitle>
            </CardHeader>
            <CardContent>
              {singlePreview.columns.length === 0 ? (
                <div className="text-xs text-muted-foreground">暂无可预览内容</div>
              ) : (
                <div className="max-h-[620px] overflow-auto rounded-lg border border-border/50">
                  <table className="min-w-max text-sm">
                    <thead className="sticky top-0 bg-muted/80 backdrop-blur z-10">
                      <tr className="h-9 border-b bg-muted/30">
                        {previewColumns.map((c) => (
                          <th key={c} className="text-left px-3 text-xs font-medium text-muted-foreground whitespace-nowrap">
                            {c === "产品ID" ? (
                              c
                            ) : (
                              <button type="button" className="inline-flex items-center gap-1 hover:text-foreground" onClick={() => handleSingleSort(c)}>
                                <span>{c}</span>
                                {singleSortKey === c ? <span>{singleSortDir === "desc" ? "↓" : "↑"}</span> : <span>↕</span>}
                              </button>
                            )}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sortedSingleRows.slice(0, 300).map((row: any, idx: number) => (
                        <tr key={`sp-${idx}`} className="h-8 border-b last:border-0">
                          {previewColumns.map((c) => (
                            <td key={c} className="h-8 py-0 px-3 text-xs whitespace-nowrap align-middle">
                              {String(row?.[c] ?? "")}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      ) : (
        <div className="grid grid-cols-12 gap-6">
          {/* Left: Product List */}
          <div className="col-span-3">
            <Card className="h-[980px]">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">产品列表{diagnosisOutput ? `（${diagnosisOutput}）` : ""}</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1.5 h-[calc(760px-72px)] overflow-y-auto pr-1">
                {filteredRows.map((result, i) => (
                  <button
                    key={i}
                    onClick={() => setSelectedProduct(i)}
                    className={`w-full text-left px-3 py-3 rounded-lg text-sm transition-all ${
                      selectedProduct === i
                        ? "bg-primary/5 border border-primary/20"
                        : "hover:bg-accent/50 border border-transparent"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="text-xs font-medium">{result.product}</div>
                        <div className="text-[10px] text-muted-foreground mt-0.5">{result.id}</div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={`text-sm font-bold ${getScoreColor(result.score)}`}>{result.score}</span>
                      </div>
                    </div>
                  </button>
                ))}
              </CardContent>
            </Card>
          </div>

          {/* Right: Diagnosis Detail */}
          <div className="col-span-9 space-y-6">
            {/* Score Card */}
            <Card>
              <CardContent className="py-6">
                <div className="flex items-center gap-8">
                  <div className="relative w-28 h-28 shrink-0">
                    <svg className="w-28 h-28 -rotate-90" viewBox="0 0 120 120">
                      <circle cx="60" cy="60" r="52" fill="none" stroke="#e5e7eb" strokeWidth="8" />
                      <circle
                        cx="60" cy="60" r="52" fill="none"
                        stroke={getScoreRingColor(selected.score)}
                        strokeWidth="8"
                        strokeLinecap="round"
                        strokeDasharray={`${(selected.score / 100) * 327} 327`}
                      />
                    </svg>
                    <div className="absolute inset-0 flex flex-col items-center justify-center">
                      <span className={`text-2xl font-bold ${getScoreColor(selected.score)}`}>{selected.score}</span>
                      <span className="text-[10px] text-muted-foreground">健康分</span>
                    </div>
                  </div>

                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2 flex-wrap">
                      <h2 className="text-lg font-bold">{selected.product}</h2>
                      <Badge variant="outline" className={`${levelInfo.color} border text-xs`}>
                        <levelInfo.icon className="w-3 h-3 mr-1" />
                        {levelInfo.label}
                      </Badge>
                      <Badge variant="outline" className="text-xs">建议动作：{selected.action}</Badge>
                      {selected.status ? (
                        <Badge
                          variant="outline"
                          className="text-xs cursor-help"
                          title={statusHintMap[selected.status] || "该状态表示当前产品在诊断分层中的位置。"}
                        >
                          状态：{selected.status}
                        </Badge>
                      ) : null}
                      {selected.group ? (
                        <Badge
                          variant="outline"
                          className="text-xs cursor-help"
                          title={groupHintMap[selected.group] || "该分组表示新品阶段的跟进优先级。"}
                        >
                          分组：{selected.group}
                        </Badge>
                      ) : null}
                      <Badge variant="outline" className={`text-xs ${selected.chuangStatus === "投放中" ? "bg-emerald-50 text-emerald-700 border-emerald-200" : selected.chuangStatus === "未投放" ? "bg-slate-50 text-slate-700 border-slate-200" : ""}`}>
                        橱窗状态：{selected.chuangStatus}
                      </Badge>
                      <Badge variant="outline" className={`text-xs ${selected.p4pStatus === "投放中" ? "bg-emerald-50 text-emerald-700 border-emerald-200" : selected.p4pStatus === "未投放" ? "bg-slate-50 text-slate-700 border-slate-200" : ""}`}>
                        P4P状态：{selected.p4pStatus}
                      </Badge>
                    </div>

                    <div className="grid grid-cols-4 gap-4 mt-4">
                      <div className="p-3 bg-muted/30 rounded-lg">
                        <div className="flex items-center gap-1.5 mb-1">
                          <Eye className="w-3.5 h-3.5 text-muted-foreground" />
                          <span className="text-[10px] text-muted-foreground">曝光量</span>
                        </div>
                        <span className="text-sm font-semibold">{selected.metrics.exposure.toLocaleString()}</span>
                      </div>
                      <div className="p-3 bg-muted/30 rounded-lg">
                        <div className="flex items-center gap-1.5 mb-1">
                          <MousePointer className="w-3.5 h-3.5 text-muted-foreground" />
                          <span className="text-[10px] text-muted-foreground">点击率</span>
                        </div>
                        <span className="text-sm font-semibold">{selected.metrics.clickRate}</span>
                      </div>
                      <div className="p-3 bg-muted/30 rounded-lg">
                        <div className="flex items-center gap-1.5 mb-1">
                          <MessageSquare className="w-3.5 h-3.5 text-muted-foreground" />
                          <span className="text-[10px] text-muted-foreground">询盘率</span>
                        </div>
                        <span className="text-sm font-semibold">{selected.metrics.inquiryRate}</span>
                      </div>
                      <div className="p-3 bg-muted/30 rounded-lg">
                        <div className="flex items-center gap-1.5 mb-1">
                          <TrendingUp className="w-3.5 h-3.5 text-muted-foreground" />
                          <span className="text-[10px] text-muted-foreground">趋势</span>
                        </div>
                        <span className="text-sm font-semibold">
                          {selected.metrics.trend === "up" ? "上升" : selected.metrics.trend === "down" ? "下降" : "稳定"}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>

            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-6">
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm">关键词（曝光&gt;10 且点击≠0）</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="max-h-[280px] overflow-auto rounded-lg border border-border/50">
                      <table className="w-full text-xs">
                        <thead className="sticky top-0 bg-muted/80">
                          <tr className="border-b bg-muted/40">
                            <th className="text-left py-2 px-2">关键词</th>
                            <th className="text-right py-2 px-2">曝光</th>
                            <th className="text-right py-2 px-2">点击</th>
                            <th className="text-right py-2 px-2">商详访客</th>
                            <th className="text-right py-2 px-2">询盘</th>
                          </tr>
                        </thead>
                        <tbody>
                          {kwClickableRows.length === 0 ? (
                            <tr><td colSpan={5} className="py-6 text-center text-muted-foreground">{product360Loading ? "加载中..." : "暂无数据"}</td></tr>
                          ) : kwClickableRows.map((r, i) => (
                            <tr key={`kw-l-${i}`} className="border-b last:border-0">
                              <td className="py-2 px-2">{String(r?.关键词 || "")}</td>
                              <td className="py-2 px-2 text-right">{Number(r?.曝光 || 0).toLocaleString()}</td>
                              <td className="py-2 px-2 text-right">{Number(r?.点击 || 0).toLocaleString()}</td>
                              <td className="py-2 px-2 text-right">{Number(r?.商详访客 || 0).toLocaleString()}</td>
                              <td className="py-2 px-2 text-right">{Number(r?.询盘 || 0).toLocaleString()}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm">关键词（曝光&gt;10 且点击=0）</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="max-h-[280px] overflow-auto rounded-lg border border-border/50">
                      <table className="w-full text-xs">
                        <thead className="sticky top-0 bg-muted/80">
                          <tr className="border-b bg-muted/40">
                            <th className="text-left py-2 px-2">关键词</th>
                            <th className="text-right py-2 px-2">曝光</th>
                            <th className="text-right py-2 px-2">点击</th>
                            <th className="text-right py-2 px-2">商详访客</th>
                            <th className="text-right py-2 px-2">询盘</th>
                          </tr>
                        </thead>
                        <tbody>
                          {kwNoClickRows.length === 0 ? (
                            <tr><td colSpan={5} className="py-6 text-center text-muted-foreground">{product360Loading ? "加载中..." : "暂无数据"}</td></tr>
                          ) : kwNoClickRows.map((r, i) => (
                            <tr key={`kw-r-${i}`} className="border-b last:border-0">
                              <td className="py-2 px-2">{String(r?.关键词 || "")}</td>
                              <td className="py-2 px-2 text-right">{Number(r?.曝光 || 0).toLocaleString()}</td>
                              <td className="py-2 px-2 text-right">{Number(r?.点击 || 0).toLocaleString()}</td>
                              <td className="py-2 px-2 text-right">{Number(r?.商详访客 || 0).toLocaleString()}</td>
                              <td className="py-2 px-2 text-right">{Number(r?.询盘 || 0).toLocaleString()}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>
              </div>

              <div className="grid grid-cols-2 gap-6">
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm">访客地域</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="max-h-[280px] overflow-auto rounded-lg border border-border/50">
                      <table className="w-full text-xs">
                        <thead className="sticky top-0 bg-muted/80">
                          <tr className="border-b bg-muted/40">
                            <th className="text-left py-2 px-2">国家</th>
                            <th className="text-right py-2 px-2">访客数</th>
                          </tr>
                        </thead>
                        <tbody>
                          {regionRows.length === 0 ? (
                            <tr><td colSpan={2} className="py-6 text-center text-muted-foreground">{product360Loading ? "加载中..." : "暂无数据"}</td></tr>
                          ) : regionRows.map((r, i) => (
                            <tr key={`region-${i}`} className="border-b last:border-0">
                              <td className="py-2 px-2">{String(r?.国家 || "")}</td>
                              <td className="py-2 px-2 text-right">{Number(r?.访客数 || 0).toLocaleString()}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm">流量来源（最新日期）</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="max-h-[280px] overflow-auto rounded-lg border border-border/50">
                      <table className="w-full text-xs">
                        <thead className="sticky top-0 bg-muted/80">
                          <tr className="border-b bg-muted/40">
                            <th className="text-left py-2 px-2">流量渠道类型</th>
                            <th className="text-right py-2 px-2">店铺访问人数</th>
                            <th className="text-right py-2 px-2">询盘人数</th>
                            <th className="text-right py-2 px-2">TM咨询人数</th>
                          </tr>
                        </thead>
                        <tbody>
                          {trafficSourceRows.length === 0 ? (
                            <tr><td colSpan={4} className="py-6 text-center text-muted-foreground">{product360Loading ? "加载中..." : "暂无数据"}</td></tr>
                          ) : trafficSourceRows.map((r, i) => (
                            <tr key={`source-${i}`} className="border-b last:border-0">
                              <td className="py-2 px-2">{String(r?.流量渠道类型 || "")}</td>
                              <td className="py-2 px-2 text-right">{Number(r?.店铺访问人数 || 0).toLocaleString()}</td>
                              <td className="py-2 px-2 text-right">{Number(r?.询盘人数 || 0).toLocaleString()}</td>
                              <td className="py-2 px-2 text-right">{Number(r?.TM咨询人数 || 0).toLocaleString()}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>
              </div>
            </div>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">诊断规则</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-4">
                  {diagnosisRules.map((rule) => (
                    <div key={rule.id} className="p-3 bg-muted/30 rounded-lg">
                      <h4 className="text-sm font-semibold mb-1.5">{rule.name}</h4>
                      <p className="text-xs text-muted-foreground mb-2.5 leading-relaxed">{rule.desc}</p>
                      <div className="space-y-1.5">
                        {rule.conditions.map((cond, i) => (
                          <div key={i} className="text-xs text-muted-foreground font-mono pl-2.5 border-l-2 border-border leading-relaxed">
                            {cond}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}
