/**
 * Dashboard - 控制台首页
 * 对接后端: /api/analysis/overview
 * 展示系统概览和各模块入口
 *
 * 【如何修改】
 * - 修改模块卡片 → 修改 modules 数组
 * - 修改统计指标 → 修改 stats 数组和 overview 数据映射
 * - 修改功能特性 → 修改 features 数组
 */
import { useState, useEffect, useRef } from "react";
import { Link, useLocation } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { motion } from "framer-motion";
import { analysisApi, configApi, dataApi, imageApi, uploadApi, membershipApi, videoBindApi } from "@/lib/api";
import { getConfigSectionSync } from "@/contexts/ConfigContext";
import { toast } from "sonner";
import {
  Upload,
  Image,
  Download,
  BarChart3,
  Package,
  ArrowRight,
  TrendingUp,
  Search,
  Store,
  Activity,
  Stethoscope,
  Settings,
  FileText,
  Layers,
  Zap,
  Shield,
  Clock,
  CheckCircle2,
  Medal,
  Star,
} from "lucide-react";

const modules = [
  {
    title: "店铺诊断",
    desc: "点击查看详细店铺诊断及解决方案",
    icon: TrendingUp,
    color: "from-blue-500/10 to-blue-600/5",
    iconColor: "text-blue-600",
    iconBg: "bg-blue-50",
    links: [
      { label: "自动发品", href: "/product-upload", icon: Package },
      { label: "配置管理", href: "/product-config", icon: Settings },
    ],
  },
  {
    title: "P4P分析",
    desc: "展示有询盘与低点击无询盘产品，点击查看详情",
    icon: BarChart3,
    color: "from-cyan-500/10 to-cyan-600/5",
    iconColor: "text-cyan-600",
    iconBg: "bg-cyan-50",
    links: [],
  },
  {
    title: "产品综合排名", 
    desc: "产品综合搜索排名1000以内的产品，点击查看详情",
    icon: Medal,
    color: "from-emerald-500/10 to-emerald-600/5",
    iconColor: "text-emerald-600",
    iconBg: "bg-emerald-50",
    links: [],
  },
  {
    title: "产品异动数据",
    desc: "全店异动最明显的产品，点击查看详情",
    icon: Activity,
    color: "from-amber-500/10 to-amber-600/5",
    iconColor: "text-amber-600",
    iconBg: "bg-amber-50",
    links: [],
  },
  {
    title: "推荐关注产品",
    desc: "综合评分表现为“推荐”的产品和新发产品，点击查看综合评分详情",
    icon: Star,
    color: "from-violet-500/10 to-violet-600/5",
    iconColor: "text-violet-600",
    iconBg: "bg-violet-50",
    links: [],
  },
];

const features = [
  { icon: Zap, title: "自动化发品", desc: "7步自动化流程，属性融合、阶梯价格一键完成" },
  { icon: Shield, title: "智能诊断", desc: "多维指标健康度评估，自动生成优化建议" },
  { icon: Clock, title: "定时采集", desc: "自动翻页下载，增量更新，避免重复数据" },
  { icon: CheckCircle2, title: "规范管理", desc: "图片自动分组、场景识别、命名规范化" },
];

const containerVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.08 } },
};
const itemVariants = {
  hidden: { opacity: 0, y: 16 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0, 0, 0.2, 1] as const } },
};

export default function Dashboard() {
  const [, setLocation] = useLocation();
  const [overview, setOverview] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [busyText, setBusyText] = useState("");
  const [activeJob, setActiveJob] = useState<"publish" | "image" | "ai_gen" | "download" | "analyze" | "">("");
  const [trafficFullLoading, setTrafficFullLoading] = useState(false);
  const [trafficFullText, setTrafficFullText] = useState("");
  const [p4pLoading, setP4pLoading] = useState(false);
  const [p4pWithInquiryRows, setP4pWithInquiryRows] = useState<any[]>([]);
  const [p4pLowClickRows, setP4pLowClickRows] = useState<any[]>([]);
  const [rankLoading, setRankLoading] = useState(false);
  const [rankRows, setRankRows] = useState<Array<{ id: string; level: string; rank: string }>>([]);
  const [anomalyLoading, setAnomalyLoading] = useState(false);
  const [anomalyUpRows, setAnomalyUpRows] = useState<Array<{ productId: string; shopExposure: number; p4pExposure: number; searchExposure: number; naturalExposure: number }>>([]);
  const [anomalyDownRows, setAnomalyDownRows] = useState<Array<{ productId: string; shopExposure: number; p4pExposure: number; searchExposure: number; naturalExposure: number }>>([]);
  const [focusLoading, setFocusLoading] = useState(false);
  const [focusPushRows, setFocusPushRows] = useState<Array<{ productId: string; score: number | string; ctr: string; inquiryRate: string }>>([]);
  const [focusNewRows, setFocusNewRows] = useState<Array<Record<string, any>>>([]);
  const [focusNewCols, setFocusNewCols] = useState<string[]>([]);
  const [publishModeDialogOpen, setPublishModeDialogOpen] = useState(false);
  const [imageJobDialogOpen, setImageJobDialogOpen] = useState(false);
  const [imageJobMode, setImageJobMode] = useState<"normalize" | "ai_gen">("normalize");
  const [publishMode, setPublishMode] = useState<"batch" | "scheduled">("batch");
  const [scheduledTime, setScheduledTime] = useState("22:00");
  const [publishRunning, setPublishRunning] = useState(false);
  const [publishRunMode, setPublishRunMode] = useState<"batch" | "scheduled" | "">("");
  const cancelRef = useRef(false);
  const publishCancelRef = useRef(false);
  const PUBLISH_MODE_STORE_KEY = "dashboard_publish_mode";

  const unwrapConfig = (raw: any) => raw?.data || raw;

  const [sharedCfg, setSharedCfg] = useState<any>(() => unwrapConfig(configApi.getCached()));

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const sections = await configApi.getSections(["data_analysis", "data_download"]);
        if (!cancelled) {
          setSharedCfg((prev: any) => ({ ...(prev || {}), ...sections }));
        }
      } catch {
        const cached = unwrapConfig(configApi.getCached());
        if (!cancelled && cached) setSharedCfg(cached);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

  const getAgentIdentity = () => {
    const key = "agent_id";
    const stored = localStorage.getItem(key) || "";
    if (stored) return stored;
    const next = `agent-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    localStorage.setItem(key, next);
    return next;
  };

  const readPolicy = async () => {
    const adminKey = localStorage.getItem("control_admin_key") || "";
    if (!adminKey) return null;
    const agentId = getAgentIdentity();
    try {
      const p = await membershipApi.resolveAgentPolicy({ agent_id: agentId, adminKey });
      return p || null;
    } catch {
      return null;
    }
  };

  const waitTask = async (taskType: string, label: string) => {
    setBusyText(`正在执行：${label}`);
    for (let i = 0; i < 600; i++) {
      if (cancelRef.current) throw new Error("已停止执行");
      const res = await dataApi.getDownloadStatus(taskType);
      const payload = res?.data || res;
      const st = payload?.data || payload;
      const s = st?.status;
      if (s === "completed" || s === "idle") return;
      if (s === "failed") throw new Error(`${label}失败`);
      await sleep(2000);
    }
    throw new Error(`${label}超时`);
  };

  const waitAnalysis = async (taskType: string, label: string) => {
    setBusyText(`正在执行：${label}`);
    for (let i = 0; i < 600; i++) {
      if (cancelRef.current) throw new Error("已停止执行");
      const res = await analysisApi.getStatus(taskType);
      const payload = res?.data || res;
      const st = payload?.data || payload;
      const s = st?.status;
      if (s === "completed" || s === "idle") return;
      if (s === "failed") throw new Error(`${label}失败`);
      await sleep(2000);
    }
    throw new Error(`${label}超时`);
  };

  const waitUploadFlowDone = async (label: string) => {
    setBusyText(`正在执行：${label}`);
    for (let i = 0; i < 3600; i++) {
      if (publishCancelRef.current) throw new Error("已停止执行");
      const res = await uploadApi.getStatus();
      const payload = res?.data || res;
      const st = payload?.data || payload;
      const s = String(st?.status || "idle").toLowerCase();
      if (["completed", "idle", "stopped"].includes(s)) return;
      if (["failed", "error"].includes(s)) throw new Error(st?.error || `${label}失败`);
      await sleep(2000);
    }
    throw new Error(`${label}超时`);
  };

  const waitOptimizeFlowDone = async (label: string) => {
    setBusyText(`正在执行：${label}`);
    for (let i = 0; i < 3600; i++) {
      if (publishCancelRef.current) throw new Error("已停止执行");
      const res = await uploadApi.getOptimizeStatus();
      const payload = res?.data || res;
      const st = payload?.data || payload;
      const s = String(st?.status || "idle").toLowerCase();
      if (["completed", "idle", "stopped"].includes(s)) return;
      if (["failed", "error"].includes(s)) throw new Error(st?.error || `${label}失败`);
      await sleep(2000);
    }
    throw new Error(`${label}超时`);
  };

  const waitVideoBindFlowDone = async (label: string) => {
    setBusyText(`正在执行：${label}`);
    for (let i = 0; i < 3600; i++) {
      if (publishCancelRef.current) throw new Error("已停止执行");
      const res = await videoBindApi.getStatus();
      const payload = res?.data || res;
      const st = payload?.data || payload;
      const s = String(st?.status || "idle").toLowerCase();
      if (["completed", "idle", "stopped"].includes(s)) return;
      if (["failed", "error"].includes(s)) throw new Error(st?.error || `${label}失败`);
      await sleep(2000);
    }
    throw new Error(`${label}超时`);
  };

  const startAutoPublish = async (mode: "batch" | "scheduled", timeText?: string) => {
    try {
      publishCancelRef.current = false;
      setPublishRunning(true);
      setPublishRunMode(mode);
      localStorage.setItem(PUBLISH_MODE_STORE_KEY, mode);
      setBusyText(mode === "scheduled" ? `定时发品中，开始时间 ${timeText || scheduledTime}` : "正在执行：自动发品");
      setBusyText("正在执行：自动发品（步骤1/3）");
      await uploadApi.start({ mode, scheduled_time: mode === "scheduled" ? (timeText || scheduledTime) : undefined });
      await waitUploadFlowDone("自动发品（步骤1/3）");

      setBusyText("正在执行：优化产品（步骤2/3）");
      await uploadApi.startOptimize({});
      await waitOptimizeFlowDone("优化产品（步骤2/3）");

      setBusyText("正在执行：新品绑定视频（步骤3/3）");
      await videoBindApi.start({});
      await waitVideoBindFlowDone("新品绑定视频（步骤3/3）");

      if (mode === "scheduled") {
        toast.warning("三步流程执行完成：自动发品→优化产品→新品绑定视频（定时模式）");
      } else {
        toast.success("三步流程执行完成：自动发品→优化产品→新品绑定视频");
      }
    } catch (e: any) {
      if (!String(e?.message || "").includes("已停止执行")) {
        toast.error(e?.message || "自动发品启动失败");
      }
    } finally {
      setPublishRunning(false);
      setPublishRunMode("");
      localStorage.removeItem(PUBLISH_MODE_STORE_KEY);
      setBusyText("");
    }
  };

  const handleAutoPublish = async () => {
    setPublishMode("batch");
    setScheduledTime("22:00");
    setPublishModeDialogOpen(true);
  };

  const handleOpenImageJobDialog = () => {
    setImageJobMode("normalize");
    setImageJobDialogOpen(true);
  };

  const startImageJob = async (mode: "normalize" | "ai_gen") => {
    try {
      cancelRef.current = false;
      setBusy(true);
      if (mode === "normalize") {
        setActiveJob("image");
        setBusyText("正在执行：图片规范化");
        await imageApi.startNormalize({});
        toast.success("已启动图片规范化");
      } else {
        setActiveJob("ai_gen");
        setBusyText("正在执行：AI 生图");
        await imageApi.startAiGen();
        toast.success("已启动 AI 生图");
      }
    } catch (e: any) {
      toast.error(e?.message || (mode === "normalize" ? "图片规范化启动失败" : "AI 生图启动失败"));
    } finally {
      setBusy(false);
      setActiveJob("");
      setBusyText("");
    }
  };

  const handleAutoDownload = async () => {
    try {
      const policy = await readPolicy();
      if (policy && policy.allow_download === false) {
        toast.error("总部策略已禁用【自动下载数据】");
        return;
      }

      cancelRef.current = false;
      setBusy(true);
      setActiveJob("download");
      const storeOverview = (await configApi.getSection("store_overview")) || {};
      const periodType = storeOverview?.period_type || "week";

      setBusyText("正在下载：店铺运营数据");
      await dataApi.startDownload({ task_type: "store_overview", period_type: periodType });
      await waitTask("store_overview", "店铺运营数据");

      setBusyText("正在下载：流量渠道数据");
      await dataApi.startDownload({ task_type: "traffic_channel" });
      await waitTask("traffic_channel", "流量渠道数据");

      setBusyText("正在下载：产品运营数据");
      await dataApi.startDownload({ task_type: "product_operate" });
      await waitTask("product_operate", "产品运营数据");

      setBusyText("正在下载：关键词数据");
      await dataApi.startDownload({ task_type: "keyword_crawler" });
      await waitTask("keyword_crawler", "关键词数据");

      setBusyText("正在下载：产品参谋日数据");
      await dataApi.startDownload({ task_type: "daily_data" });
      await waitTask("daily_data", "产品参谋日数据");

      setBusyText("正在下载：产品360数据（采集+生成Excel）");
      await dataApi.startDownload({ task_type: "product360" });
      await waitTask("product360", "产品360数据");

      toast.success("自动下载数据执行完成");
    } catch (e: any) {
      toast.error(e?.message || "自动下载数据失败");
    } finally {
      setBusy(false);
      setActiveJob("");
      setBusyText("");
    }
  };

  const handleAutoAnalyze = async () => {
    try {
      const policy = await readPolicy();
      if (policy && policy.allow_analysis === false) {
        toast.error("总部策略已禁用【自动分析数据】");
        return;
      }

      cancelRef.current = false;
      setBusy(true);
      setActiveJob("analyze");

      setBusyText("正在分析：综合分析");
      await analysisApi.start({ task_type: "comprehensive" });
      await waitAnalysis("comprehensive", "综合分析");

      setBusyText("正在分析：单品分析");
      await analysisApi.start({ task_type: "single_analysis" });
      await waitAnalysis("single_analysis", "单品分析");

      setBusyText("正在分析：流量分析");
      await analysisApi.start({ task_type: "traffic_ai" });
      await waitAnalysis("traffic_ai", "流量分析");

      setBusyText("正在分析：产品优化建议");
      await analysisApi.start({ task_type: "title_optimize", source_file: "" });
      await waitAnalysis("title_optimize", "产品优化建议");

      toast.success("自动分析数据执行完成");
    } catch (e: any) {
      toast.error(e?.message || "自动分析数据失败");
    } finally {
      setBusy(false);
      setActiveJob("");
      setBusyText("");
    }
  };

  const handleStopActive = async () => {
    try {
      cancelRef.current = true;
      publishCancelRef.current = true;
      if (publishRunning || activeJob === "publish") {
        await uploadApi.stop();
      } else if (activeJob === "image") {
        await imageApi.stopNormalize();
      } else if (activeJob === "ai_gen") {
        await imageApi.stopAiGen();
      } else if (activeJob === "download") {
        await Promise.allSettled([
          dataApi.stopDownload("store_overview"),
          dataApi.stopDownload("traffic_channel"),
          dataApi.stopDownload("product_operate"),
          dataApi.stopDownload("keyword_crawler"),
          dataApi.stopDownload("daily_data"),
          dataApi.stopDownload("product360"),
        ]);
      } else if (activeJob === "analyze") {
        await Promise.allSettled([
          analysisApi.stop("comprehensive"),
          analysisApi.stop("single_analysis"),
          analysisApi.stop("traffic_ai"),
          analysisApi.stop("title_optimize"),
        ]);
      }
      toast.info("已停止执行");
    } catch (e: any) {
      toast.error(e?.message || "停止失败");
    } finally {
      setBusy(false);
      setActiveJob("");
      setBusyText("");
    }
  };

  const handleModuleJump = (title: string) => {
    if (title === "店铺诊断") {
      setLocation("/traffic-analysis");
      return;
    }
    if (title === "P4P分析") {
      setLocation("/p4p-analysis");
      return;
    }
    if (title === "产品综合排名") {
      setLocation("/data-download");
      return;
    }
    if (title === "产品异动数据") {
      setLocation("/data-analysis?tab=anomaly");
      return;
    }
    if (title === "推荐关注产品") {
      setLocation("/product-diagnosis");
    }
  };

  useEffect(() => {
    analysisApi.getOverview().then((res: any) => {
      setOverview(res?.data || res);
    }).catch(() => {});
  }, []);

  // 页面刷新后恢复自动发品状态：后端任务还在跑时，按钮应继续显示“发布中/定时发品中”
  useEffect(() => {
    let destroyed = false;

    const syncPublishState = async () => {
      try {
        const res = await uploadApi.getStatus();
        const payload = res?.data || res;
        const st = payload?.data || payload;
        const s = String(st?.status || "idle").toLowerCase();

        const running = ["running", "pending", "paused"].includes(s);
        if (!destroyed) {
          setPublishRunning(running);
          if (running) {
            const storedMode = (localStorage.getItem(PUBLISH_MODE_STORE_KEY) || "").trim();
            setPublishRunMode(storedMode === "scheduled" ? "scheduled" : "batch");
          } else {
            setPublishRunMode("");
            localStorage.removeItem(PUBLISH_MODE_STORE_KEY);
          }
        }
      } catch {
        // ignore
      }
    };

    void syncPublishState();
    return () => {
      destroyed = true;
    };
  }, []);

  useEffect(() => {
    if (!publishRunning) return;
    let destroyed = false;

    const syncPublishState = async () => {
      try {
        const res = await uploadApi.getStatus();
        const payload = res?.data || res;
        const st = payload?.data || payload;
        const s = String(st?.status || "idle").toLowerCase();

        const running = ["running", "pending", "paused"].includes(s);
        if (!destroyed) {
          setPublishRunning(running);
          if (running) {
            const storedMode = (localStorage.getItem(PUBLISH_MODE_STORE_KEY) || "").trim();
            setPublishRunMode(storedMode === "scheduled" ? "scheduled" : "batch");
          } else {
            setPublishRunMode("");
            localStorage.removeItem(PUBLISH_MODE_STORE_KEY);
          }
        }
      } catch {
        // ignore
      }
    };

    const timer = setInterval(() => {
      // 页面不可见时暂停轮询，节省网络和服务器资源
      if (typeof document !== "undefined" && document.visibilityState !== "visible") return;
      syncPublishState();
    }, 4000);
    return () => {
      destroyed = true;
      clearInterval(timer);
    };
  }, [publishRunning]);

  useEffect(() => {
    const loadTrafficFull = async () => {
      try {
        setTrafficFullLoading(true);
        const res = await analysisApi.getTrafficAiResult();
        const payload = res?.data || res;
        const data = payload?.data || payload;
        const txt = String(data?.content || "");

        const cleaned = txt
          .replace(/\n*---\n【结果校验告警】[\s\S]*$/m, "")
          .trim();

        // 提取「模块9」完整区块（含标题+正文），兼容 markdown 标题/空格差异
        let full = "";
        const lines = cleaned.split(/\r?\n/);
        const isModuleLine = (s: string) => {
          const x = String(s || "").replace(/^\s*#{1,6}\s*/, "").trim();
          return /^模块\s*\d+/.test(x);
        };

        let start = -1;
        let end = lines.length;
        for (let i = 0; i < lines.length; i += 1) {
          const x = String(lines[i] || "").replace(/^\s*#{1,6}\s*/, "").trim();
          if (/^模块\s*9\b/.test(x) || /^模块\s*9[:：]/.test(x)) {
            start = i;
            break;
          }
        }
        if (start >= 0) {
          for (let j = start + 1; j < lines.length; j += 1) {
            if (isModuleLine(lines[j])) {
              end = j;
              break;
            }
          }
          full = lines.slice(start, end).join("\n").trim();
        }

        setTrafficFullText(full || "暂无模块9内容，请先在流量分析页执行分析。");
      } catch {
        setTrafficFullText("暂无完整分析结果，请先在流量分析页执行分析。");
      } finally {
        setTrafficFullLoading(false);
      }
    };

    loadTrafficFull();
  }, []);

  const renderTrafficFull = (text: string) => {
    const lines = String(text || "").split(/\r?\n/);
    const out: Array<any> = [];

    for (let i = 0; i < lines.length; i += 1) {
      const raw = lines[i] || "";
      const t = raw.trim();
      if (!t) continue;

      const plain = t.replace(/^\s*#{1,6}\s*/, "").trim();

      if (/^模块\s*9/.test(plain)) {
        continue;
      }

      if (/^【.+】$/.test(plain) || /^([一二三四五六七八九十]+、|\d+\.\d+|\d+\.)/.test(plain)) {
        out.push(
          <div key={`h-${i}`} className="text-sm font-semibold mt-3 mb-1">
            {plain}
          </div>
        );
        continue;
      }

      if (/^[\-•]/.test(plain)) {
        out.push(
          <div key={`li-${i}`} className="text-sm leading-7 pl-3">
            {plain}
          </div>
        );
        continue;
      }

      out.push(
        <div key={`p-${i}`} className="text-sm leading-7">
          {plain}
        </div>
      );
    }

    return <div className="space-y-1">{out}</div>;
  };

  useEffect(() => {
    if (!sharedCfg) return;

    const loadP4PBlocks = async () => {
      try {
        setP4pLoading(true);
        const p4pSourceDir =
          sharedCfg?.data_analysis?.p4p_source_dir ||
          getConfigSectionSync("data_analysis")?.p4p_source_dir ||
          "";

        if (!p4pSourceDir) {
          return;
        }

        const filesRes = await dataApi.getFiles(p4pSourceDir);
        const filesPayload = filesRes?.data ?? filesRes;
        const files = Array.isArray(filesPayload) ? filesPayload : filesPayload?.data || [];
        const excelFiles = (files || [])
          .filter((f: any) => /\.(xlsx|xls)$/i.test(String(f?.name || "")))
          .filter((f: any) => !String(f?.name || "").startsWith("~$"));

        if (!excelFiles.length) {
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

        const latestPath = String(sorted[0]?.path || "");
        const tableRes = await analysisApi.getP4pTable(latestPath || undefined, undefined);
        const payload = tableRes?.data || tableRes;
        const data = payload?.data || payload;
        const rows = Array.isArray(data?.rows) ? data.rows : [];
        const cols: string[] = Array.isArray(data?.columns) ? data.columns : [];

        const toNum = (v: any) => {
          const n = Number(String(v ?? "0").replace(/,/g, "").replace(/%/g, "").trim());
          return Number.isFinite(n) ? n : 0;
        };

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
          .map((r: any) => ({
            产品ID: String(byNameOrIndex(r, ["产品ID"], 0) ?? "").replace(/\.0+$/, "").trim(),
            计划ID: String(byNameOrIndex(r, ["计划ID"], 2) ?? "").trim(),
            曝光量: toNum(byNameOrIndex(r, ["曝光量"], 8)),
            点击量: toNum(byNameOrIndex(r, ["点击量"], 9)),
            点击率: toNum(byNameOrIndex(r, ["点击率"], 10)),
            全站商机量: toNum(byNameOrIndex(r, ["全站商机量"], 11)),
            L1全站商机量: toNum(byNameOrIndex(r, ["L1+全站商机量"], 12)),
            全站商机转化率: String(byNameOrIndex(r, ["全站商机转化率"], 13) ?? ""),
          }))
          .filter((r: any) => r.曝光量 >= 60);

        const withInquiry = mapped
          .filter((r: any) => r.全站商机量 >= 1)
          .sort((a: any, b: any) => b.全站商机量 - a.全站商机量)
          .slice(0, 8);

        const lowClick = mapped
          .filter((r: any) => r.全站商机量 < 1 && r.点击率 < 2)
          .sort((a: any, b: any) => b.曝光量 - a.曝光量)
          .slice(0, 8);

        setP4pWithInquiryRows(withInquiry);
        setP4pLowClickRows(lowClick);
      } catch {
        // 保留已有 P4P 概览数据
      } finally {
        setP4pLoading(false);
      }
    };

    const loadRankRows = async () => {
      try {
        setRankLoading(true);
        const excelDir =
          sharedCfg?.data_download?.product360_excel_result_dir ||
          sharedCfg?.data_download?.product360_output_dir ||
          getConfigSectionSync("data_download")?.product360_excel_result_dir ||
          getConfigSectionSync("data_download")?.product360_output_dir ||
          "";
        const res = await dataApi.getProduct360Table(excelDir, "产品详细信息");
        const payload = res?.data || res;
        const data = payload?.data || payload;
        const rows = Array.isArray(data?.rows) ? data.rows : [];
        const cols: string[] = Array.isArray(data?.columns) ? data.columns : [];
        const byIdx = (row: any, idx: number) => {
          const k = cols[idx];
          return k ? row?.[k] : undefined;
        };
        const next = rows
          .map((r: any) => ({
            id: String(r?.["产品ID"] ?? byIdx(r, 1) ?? "").trim(),
            level: String(r?.["平台内部产品分级"] ?? byIdx(r, 3) ?? "").trim(),
            rank: String(r?.["产品综合搜索排名"] ?? byIdx(r, 4) ?? "").trim(),
          }))
          .filter((r: any) => r.rank !== "")
          .sort((a: any, b: any) => {
            const aNum = Number(String(a.rank).replace(/,/g, ""));
            const bNum = Number(String(b.rank).replace(/,/g, ""));
            if (Number.isFinite(aNum) && Number.isFinite(bNum)) return aNum - bNum;
            return String(a.rank).localeCompare(String(b.rank));
          })
          .slice(0, 200);
        setRankRows(next);
      } catch {
        // 保留已有排名数据
      } finally {
        setRankLoading(false);
      }
    };

    // 两个加载函数并行执行，不再先后等待
    void Promise.all([loadP4PBlocks(), loadRankRows()]);
  }, [sharedCfg]);



  useEffect(() => {
    const loadAnomalyRows = async () => {
      try {
        setAnomalyLoading(true);
        const res = await analysisApi.getVolatilityAnomaly();
        const payload = res?.data || res;
        const data = payload?.data || payload;
        const rows = Array.isArray(data?.rows) ? data.rows : [];

        const mapped = rows.map((r: any) => ({
          productId: String(r?.productId ?? "").trim(),
          shopExposure: Number(r?.shopExposure || 0),
          p4pExposure: Number(r?.p4pExposure || 0),
          searchExposure: Number(r?.searchExposure || 0),
          naturalExposure: Number(r?.naturalExposure || 0),
        }));

        setAnomalyUpRows(
          mapped.filter((r: any) => r.shopExposure > 500).sort((a: any, b: any) => b.shopExposure - a.shopExposure).slice(0, 200)
        );
        setAnomalyDownRows(
          mapped.filter((r: any) => r.shopExposure < -500).sort((a: any, b: any) => a.shopExposure - b.shopExposure).slice(0, 200)
        );
      } catch {
        // 保留已有异动数据
      } finally {
        setAnomalyLoading(false);
      }
    };

    const t = window.setTimeout(() => {
      void loadAnomalyRows();
    }, 350);
    return () => window.clearTimeout(t);
  }, []);

  useEffect(() => {
    const loadFocusData = async () => {
      try {
        setFocusLoading(true);

        // 左侧：周数据分析中的“推进”
        const diagRes = await analysisApi.getDiagnosisTable();
        const diagPayload = diagRes?.data || diagRes;
        const diagData = diagPayload?.data || diagPayload;
        const diagRows = Array.isArray(diagData?.rows) ? diagData.rows : [];

        const pushRows = diagRows
          .filter((r: any) => String(r?.["建议动作"] ?? "").trim() === "推进")
          .map((r: any) => ({
            productId: String(r?.["产品ID"] ?? "").trim(),
            score: r?.["权重评分"] ?? "--",
            ctr: String(r?.["最近点击率"] ?? "--"),
            inquiryRate: String(r?.["修正询盘率"] ?? "--"),
          }))
          .slice(0, 200);
        setFocusPushRows(pushRows);

        // 右侧：综合分析 -> 新发链接数据监控（全店曝光次数 sheet）
        const linksRes = await analysisApi.getNewLinksMonitor(undefined, "全店曝光次数");
        const linksPayload = linksRes?.data || linksRes;
        const linksData = linksPayload?.data || linksPayload;
        const cols = Array.isArray(linksData?.columns) ? linksData.columns : [];
        const rows = Array.isArray(linksData?.rows) ? linksData.rows : [];

        const idCol = cols.includes("产品ID") ? "产品ID" : cols[0];
        const weekCols = cols.filter((c: string) => c !== idCol && c !== "异动" && c !== "涨跌" && c !== "最近橱窗状态" && c !== "最近P4P状态");
        const latest4 = weekCols.slice(-4).reverse();

        const toNum = (v: any) => {
          const n = Number(String(v ?? "").replace(/,/g, "").trim());
          return Number.isFinite(n) ? n : 0;
        };

        const newRows = rows.filter((r: any) => {
          const vals = latest4.map((c: string) => toNum(r?.[c]));
          const cnt = vals.filter((v: number) => v > 30).length;
          return cnt >= 3;
        }).slice(0, 200);

        setFocusNewCols(latest4);
        setFocusNewRows(newRows);
      } catch {
        // 保留已有重点关注数据
      } finally {
        setFocusLoading(false);
      }
    };

    const t = window.setTimeout(() => {
      void loadFocusData();
    }, 700);
    return () => window.clearTimeout(t);
  }, []);

  const stats = [
    { label: "总产品数", value: overview?.total_products ?? "--", desc: "已扫描产品", icon: BarChart3 },
    { label: "已发布", value: overview?.published_products ?? "--", desc: overview?.publish_rate || "", icon: Activity },
    { label: "待发布", value: overview?.available_products ?? "--", desc: "可立即发布", icon: Zap },
    { label: "数据源", value: "3", desc: "参谋/关键词/店铺", icon: Shield },
  ];

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 via-slate-50 to-slate-100">
      {/* Hero Section */}
      <div className="relative overflow-hidden bg-gradient-to-br from-[#1B3A5C] via-[#1e4a6e] to-[#162d48]">
        <div className="absolute top-0 right-0 w-96 h-96 bg-amber-400/5 rounded-full blur-3xl" />
        <div className="absolute bottom-0 left-1/3 w-64 h-64 bg-blue-400/5 rounded-full blur-3xl" />
        <motion.div
          className="relative z-10 px-8 py-14"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          <div className="max-w-4xl">
            <div className="flex items-center gap-2 mb-5">
              <div className="h-0.5 w-8 bg-amber-400 rounded-full" />
              <span className="text-amber-300/80 text-xs font-medium tracking-[0.2em] uppercase">
                Alibaba International Station
              </span>
            </div>
            <h1 className="text-3xl font-bold text-white mb-3 tracking-tight leading-tight">
              智能运营管理系统
            </h1>
            <p className="text-blue-100/60 text-sm max-w-xl leading-relaxed">
              整合产品上传、图片管理、数据下载与分析四大核心模块，实现阿里巴巴国际站运营全流程自动化管理
            </p>
          </div>
          <motion.div
            className="grid grid-cols-4 gap-4 mt-10 max-w-3xl"
            variants={containerVariants}
            initial="hidden"
            animate="visible"
          >
            {stats.map((stat) => (
              <motion.div
                key={stat.label}
                variants={itemVariants}
                className="bg-white/[0.07] backdrop-blur-sm rounded-xl px-4 py-4 border border-white/[0.08] hover:bg-white/[0.12] transition-colors duration-300"
              >
                <div className="flex items-center gap-2 mb-2">
                  <stat.icon className="w-3.5 h-3.5 text-amber-400/70" />
                  <span className="text-[11px] text-blue-200/60 font-medium">{stat.label}</span>
                </div>
                <div className="text-2xl font-bold text-white tracking-tight">{stat.value}</div>
                <div className="text-[10px] text-blue-200/40 mt-1">{stat.desc}</div>
              </motion.div>
            ))}
          </motion.div>
        </motion.div>
      </div>

      <Dialog modal={false} open={publishModeDialogOpen} onOpenChange={setPublishModeDialogOpen}>
        <DialogContent showOverlay={false}>
          <DialogHeader>
            <DialogTitle>选择发品模式</DialogTitle>
            <DialogDescription>请选择“立刻发品”或“定时发品”。定时模式可设置开始发品时间。</DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Button type="button" variant={publishMode === "batch" ? "default" : "outline"} onClick={() => setPublishMode("batch")}>立刻发品</Button>
              <Button type="button" variant={publishMode === "scheduled" ? "default" : "outline"} onClick={() => setPublishMode("scheduled")}>定时发品</Button>
            </div>

            {publishMode === "scheduled" && (
              <div className="space-y-2">
                <Label className="text-xs text-muted-foreground">自动发品时间</Label>
                <Input type="time" value={scheduledTime} onChange={(e) => setScheduledTime(e.target.value || "22:00")} />
                <div className="text-[11px] text-amber-600 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                  定时发品中，请勿退出软件
                </div>
              </div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setPublishModeDialogOpen(false)}>取消</Button>
            <Button
              onClick={async () => {
                const mode = publishMode;
                const timeText = scheduledTime;
                setPublishModeDialogOpen(false);
                await startAutoPublish(mode, timeText);
              }}
            >
              确认开始
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog modal={false} open={imageJobDialogOpen} onOpenChange={setImageJobDialogOpen}>
        <DialogContent showOverlay={false}>
          <DialogHeader>
            <DialogTitle>选择图片任务</DialogTitle>
            <DialogDescription>请选择要执行的图片处理类型。</DialogDescription>
          </DialogHeader>

          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant={imageJobMode === "normalize" ? "default" : "outline"}
              onClick={() => setImageJobMode("normalize")}
            >
              图片规范化
            </Button>
            <Button
              type="button"
              variant={imageJobMode === "ai_gen" ? "default" : "outline"}
              onClick={() => setImageJobMode("ai_gen")}
            >
              AI 生图
            </Button>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setImageJobDialogOpen(false)}>取消</Button>
            <Button
              onClick={async () => {
                const mode = imageJobMode;
                setImageJobDialogOpen(false);
                await startImageJob(mode);
              }}
            >
              确认开始
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {busy && (
        <div className="fixed right-6 bottom-6 z-50 pointer-events-none">
          <div className="bg-white rounded-xl shadow-xl p-4 min-w-[280px] max-w-[60vw] border border-border/50">
            <div className="text-sm font-semibold mb-1">任务执行中</div>
            <div className="text-xs text-muted-foreground">{busyText || "正在处理，请稍候..."}</div>
          </div>
        </div>
      )}

      {/* Module Cards */}
      <div className="px-8 py-8">
        <motion.div className="flex items-center gap-2 mb-8" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.3 }}>
          <FileText className="w-4.5 h-4.5 text-muted-foreground/70" />
          <h2 className="text-base font-semibold text-foreground">功能模块</h2>
          <div className="h-px flex-1 bg-border/50 ml-3" />
        </motion.div>
        <div className="mb-7 grid grid-cols-2 md:grid-cols-4 gap-4">
          <Button
            onClick={publishRunning ? handleStopActive : handleAutoPublish}
            disabled={false}
            variant="outline"
            className={`h-10 transition-colors ${publishRunning
              ? "bg-red-50 text-red-700 border-red-200 hover:bg-red-100"
              : "bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100"}`}
          >
            {publishRunning ? (publishRunMode === "scheduled" ? "定时发品中" : "发布中") : "自动发布"}
          </Button>

          <Button
            onClick={busy && (activeJob === "image" || activeJob === "ai_gen") ? handleStopActive : handleOpenImageJobDialog}
            disabled={busy && activeJob !== "image" && activeJob !== "ai_gen"}
            variant="outline"
            className={`h-10 transition-colors ${busy && (activeJob === "image" || activeJob === "ai_gen")
              ? "bg-red-50 text-red-700 border-red-200 hover:bg-red-100"
              : "bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-100"}`}
          >
            {busy && (activeJob === "image" || activeJob === "ai_gen") ? "停止" : "处理图片"}
          </Button>

          <Button
            onClick={busy && activeJob === "download" ? handleStopActive : handleAutoDownload}
            disabled={busy && activeJob !== "download"}
            variant="outline"
            className={`h-10 transition-colors ${busy && activeJob === "download"
              ? "bg-red-50 text-red-700 border-red-200 hover:bg-red-100"
              : "bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100"}`}
          >
            {busy && activeJob === "download" ? "停止" : "自动下载数据"}
          </Button>

          <Button
            onClick={busy && activeJob === "analyze" ? handleStopActive : handleAutoAnalyze}
            disabled={busy && activeJob !== "analyze"}
            variant="outline"
            className={`h-10 transition-colors ${busy && activeJob === "analyze"
              ? "bg-red-50 text-red-700 border-red-200 hover:bg-red-100"
              : "bg-violet-50 text-violet-700 border-violet-200 hover:bg-violet-100"}`}
          >
            {busy && activeJob === "analyze" ? "停止" : "自动分析数据"}
          </Button>
        </div>

        <div className="mb-4 flex items-center justify-center gap-10 text-xs text-muted-foreground">
          <div>分析流程：下载数据➡分析按钮➡查看分析结果➡查看建议</div>
          <div>行动流程：上新品➡优化产品➡绑定视频➡清除零效果产品</div>
        </div>

        <motion.div className="grid grid-cols-1 gap-8 max-w-[1400px] mx-auto" variants={containerVariants} initial="hidden" animate="visible">
          {modules.map((mod) => {
            const theme = mod.title === "店铺诊断"
              ? {
                card: "border-blue-200/80",
                header: "bg-gradient-to-r from-blue-50 to-blue-100/80 border-blue-200/70",
                block: "bg-blue-50/30 border-blue-200/70",
                subHead: "bg-blue-100/70",
              }
              : mod.title === "P4P分析"
                ? {
                  card: "border-cyan-200/80",
                  header: "bg-gradient-to-r from-cyan-50 to-cyan-100/80 border-cyan-200/70",
                  block: "bg-cyan-50/30 border-cyan-200/70",
                  subHead: "bg-cyan-100/70",
                }
                : mod.title === "产品综合排名"
                  ? {
                    card: "border-emerald-200/80",
                    header: "bg-gradient-to-r from-emerald-50 to-emerald-100/80 border-emerald-200/70",
                    block: "bg-emerald-50/30 border-emerald-200/70",
                    subHead: "bg-emerald-100/70",
                  }
                  : mod.title === "产品异动数据"
                    ? {
                      card: "border-amber-200/80",
                      header: "bg-gradient-to-r from-amber-50 to-amber-100/80 border-amber-200/70",
                      block: "bg-amber-50/30 border-amber-200/70",
                      subHead: "bg-amber-100/70",
                    }
                    : {
                      card: "border-violet-200/80",
                      header: "bg-gradient-to-r from-violet-50 to-violet-100/80 border-violet-200/70",
                      block: "bg-violet-50/30 border-violet-200/70",
                      subHead: "bg-violet-100/70",
                    };

            return (
            <motion.div key={mod.title} variants={itemVariants}>
              <Card
                className={`border bg-white/95 shadow-sm hover:shadow-md transition-all duration-300 overflow-hidden group rounded-2xl ${theme.card}`}
              >
                <CardHeader onClick={() => handleModuleJump(mod.title)} className={`pb-4 cursor-pointer border-b ${theme.header}`}>
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <div className={`w-10 h-10 rounded-xl ${mod.iconBg} shadow-sm flex items-center justify-center group-hover:scale-105 transition-transform duration-300`}>
                        <mod.icon className={`w-5 h-5 ${mod.iconColor}`} />
                      </div>
                      <div>
                        <CardTitle className="text-base font-semibold">{mod.title}</CardTitle>
                        <p className="text-xs text-muted-foreground mt-0.5">{mod.desc}</p>
                      </div>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="pt-5">
                  {mod.title === "店铺诊断" ? (
                    <div className={`rounded-xl border p-5 min-h-[420px] ${theme.block}`}>
                      <div className="flex items-center justify-between mb-4 border-b pb-3">
                        <div className="text-sm font-semibold">完整分析结果</div>
                        <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" onClick={(e) => { e.stopPropagation(); setLocation('/traffic-analysis'); }}>
                          查看更多
                        </Button>
                      </div>
                      {trafficFullLoading ? (
                        <div className="text-xs text-muted-foreground">加载中...</div>
                      ) : (
                        <div className="max-h-[460px] overflow-auto pr-1">
                          {renderTrafficFull(trafficFullText || "暂无完整分析结果")}
                        </div>
                      )}
                    </div>
                  ) : mod.title === "P4P分析" ? (
                    <div className="grid grid-cols-1 2xl:grid-cols-2 gap-5" onClick={(e) => e.stopPropagation()}>
                      <div className={`rounded-xl border overflow-hidden ${theme.block}`}>
                        <div className={`px-3 py-2 text-xs font-semibold flex items-center justify-between ${theme.subHead}`}>
                          <span>有询盘（全站商机量 ≥ 1）</span>
                          <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" onClick={(e) => { e.stopPropagation(); setLocation('/p4p-analysis'); }}>
                            查看更多
                          </Button>
                        </div>
                        <div className="max-h-[330px] overflow-auto">
                          <table className="w-full text-xs">
                            <thead className={`sticky top-0 z-10 ${theme.subHead}`}>
                              <tr className="border-b">
                                <th className="text-left px-3 py-2">产品ID</th>
                                <th className="text-right px-3 py-2">曝光量</th>
                                <th className="text-right px-3 py-2">点击量</th>
                                <th className="text-right px-3 py-2">点击率</th>
                                <th className="text-right px-3 py-2">全站商机量</th>
                              </tr>
                            </thead>
                            <tbody>
                              {p4pLoading ? (
                                <tr><td className="px-3 py-4 text-muted-foreground" colSpan={5}>加载中...</td></tr>
                              ) : p4pWithInquiryRows.length === 0 ? (
                                <tr><td className="px-3 py-4 text-muted-foreground" colSpan={5}>暂无有询盘数据</td></tr>
                              ) : p4pWithInquiryRows.map((r: any, idx: number) => (
                                <tr key={`p4p-with-${idx}`} className="border-b last:border-0">
                                  <td className="px-3 py-2 font-mono">{String(r?.产品ID ?? "--")}</td>
                                  <td className="px-3 py-2 text-right font-mono">{String(r?.曝光量 ?? 0)}</td>
                                  <td className="px-3 py-2 text-right font-mono">{String(r?.点击量 ?? 0)}</td>
                                  <td className="px-3 py-2 text-right font-mono">{`${Number(r?.点击率 ?? 0).toFixed(2)}%`}</td>
                                  <td className="px-3 py-2 text-right font-mono">{String(r?.全站商机量 ?? 0)}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>

                      <div className="rounded-lg border border-border/60 overflow-hidden">
                        <div className="px-3 py-2 text-xs font-semibold bg-muted/50 flex items-center justify-between">
                          <span>无询盘且点击率低（全站商机量 &lt; 1 且 点击率 &lt; 2.00%）</span>
                          <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" onClick={(e) => { e.stopPropagation(); setLocation('/p4p-analysis'); }}>
                            查看更多
                          </Button>
                        </div>
                        <div className="max-h-[380px] overflow-auto">
                          <table className="w-full text-xs">
                            <thead className="sticky top-0 z-10 bg-background">
                              <tr className="border-b bg-muted/20">
                                <th className="text-left px-3 py-2">产品ID</th>
                                <th className="text-right px-3 py-2">曝光量</th>
                                <th className="text-right px-3 py-2">点击量</th>
                                <th className="text-right px-3 py-2">点击率</th>
                              </tr>
                            </thead>
                            <tbody>
                              {p4pLoading ? (
                                <tr><td className="px-3 py-4 text-muted-foreground" colSpan={4}>加载中...</td></tr>
                              ) : p4pLowClickRows.length === 0 ? (
                                <tr><td className="px-3 py-4 text-muted-foreground" colSpan={4}>暂无无询盘且低点击率数据</td></tr>
                              ) : p4pLowClickRows.map((r: any, idx: number) => (
                                <tr key={`p4p-low-${idx}`} className="border-b last:border-0">
                                  <td className="px-3 py-2 font-mono">{String(r?.产品ID ?? "--")}</td>
                                  <td className="px-3 py-2 text-right font-mono">{String(r?.曝光量 ?? 0)}</td>
                                  <td className="px-3 py-2 text-right font-mono">{String(r?.点击量 ?? 0)}</td>
                                  <td className="px-3 py-2 text-right font-mono">{`${Number(r?.点击率 ?? 0).toFixed(2)}%`}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  ) : mod.title === "产品综合排名" ? (
                    <div className="rounded-lg border border-border/60 overflow-hidden">
                      <div className="max-h-[332px] overflow-auto">
                        <table className="w-full text-xs">
                          <thead className="sticky top-0 z-10 bg-background">
                            <tr className="border-b bg-muted/20">
                              <th className="text-left px-3 py-2">产品ID</th>
                              <th className="text-left px-3 py-2">平台内部产品分级</th>
                              <th className="text-left px-3 py-2">产品综合搜索排名</th>
                            </tr>
                          </thead>
                          <tbody>
                            {rankLoading ? (
                              <tr><td className="px-3 py-4 text-muted-foreground" colSpan={3}>加载中...</td></tr>
                            ) : rankRows.length === 0 ? (
                              <tr><td className="px-3 py-4 text-muted-foreground" colSpan={3}>暂无排名数据（产品综合搜索排名为空）</td></tr>
                            ) : rankRows.map((r, idx) => (
                              <tr key={`${r.id}-${idx}`} className="border-b last:border-0">
                                <td className="px-3 py-2 font-mono">{r.id || "--"}</td>
                                <td className="px-3 py-2">{r.level || "--"}</td>
                                <td className="px-3 py-2 font-mono">{r.rank || "--"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ) : mod.title === "产品异动数据" ? (
                    <div className="grid grid-cols-1 2xl:grid-cols-2 gap-5" onClick={(e) => e.stopPropagation()}>
                      <div className="rounded-lg border border-border/60 overflow-hidden">
                        <div className="px-3 py-2 text-xs font-semibold bg-muted/50 flex items-center justify-between">
                          <span>数据上升明显</span>
                          <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" onClick={(e) => { e.stopPropagation(); setLocation('/data-analysis?tab=anomaly'); }}>
                            查看更多
                          </Button>
                        </div>
                        <div className="max-h-[300px] overflow-auto">
                          <table className="w-full text-xs">
                            <thead className="sticky top-0 z-10 bg-background">
                              <tr className="border-b bg-muted/20">
                                <th className="text-left px-3 py-2">产品ID</th>
                                <th className="text-right px-3 py-2">全店曝光</th>
                                <th className="text-right px-3 py-2">全站推曝光</th>
                                <th className="text-right px-3 py-2">搜索曝光</th>
                                <th className="text-right px-3 py-2">自然曝光</th>
                              </tr>
                            </thead>
                            <tbody>
                              {anomalyLoading ? (
                                <tr><td className="px-3 py-4 text-muted-foreground" colSpan={5}>加载中...</td></tr>
                              ) : anomalyUpRows.length === 0 ? (
                                <tr><td className="px-3 py-4 text-muted-foreground" colSpan={5}>暂无数据</td></tr>
                              ) : anomalyUpRows.map((r, idx) => (
                                <tr key={`${r.productId}-up-${idx}`} className="border-b last:border-0">
                                  <td className="px-3 py-2 font-mono">{r.productId || "--"}</td>
                                  <td className="px-3 py-2 text-right font-mono">{r.shopExposure}</td>
                                  <td className="px-3 py-2 text-right font-mono">{r.p4pExposure}</td>
                                  <td className="px-3 py-2 text-right font-mono">{r.searchExposure}</td>
                                  <td className="px-3 py-2 text-right font-mono">{r.naturalExposure}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>

                      <div className="rounded-lg border border-border/60 overflow-hidden">
                        <div className="px-3 py-2 text-xs font-semibold bg-muted/50 flex items-center justify-between">
                          <span>数据下降明显</span>
                          <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" onClick={(e) => { e.stopPropagation(); setLocation('/data-analysis?tab=anomaly'); }}>
                            查看更多
                          </Button>
                        </div>
                        <div className="max-h-[300px] overflow-auto">
                          <table className="w-full text-xs">
                            <thead className="sticky top-0 z-10 bg-background">
                              <tr className="border-b bg-muted/20">
                                <th className="text-left px-3 py-2">产品ID</th>
                                <th className="text-right px-3 py-2">全店曝光</th>
                                <th className="text-right px-3 py-2">全站推曝光</th>
                                <th className="text-right px-3 py-2">搜索曝光</th>
                                <th className="text-right px-3 py-2">自然曝光</th>
                              </tr>
                            </thead>
                            <tbody>
                              {anomalyLoading ? (
                                <tr><td className="px-3 py-4 text-muted-foreground" colSpan={5}>加载中...</td></tr>
                              ) : anomalyDownRows.length === 0 ? (
                                <tr><td className="px-3 py-4 text-muted-foreground" colSpan={5}>暂无数据</td></tr>
                              ) : anomalyDownRows.map((r, idx) => (
                                <tr key={`${r.productId}-down-${idx}`} className="border-b last:border-0">
                                  <td className="px-3 py-2 font-mono">{r.productId || "--"}</td>
                                  <td className="px-3 py-2 text-right font-mono">{r.shopExposure}</td>
                                  <td className="px-3 py-2 text-right font-mono">{r.p4pExposure}</td>
                                  <td className="px-3 py-2 text-right font-mono">{r.searchExposure}</td>
                                  <td className="px-3 py-2 text-right font-mono">{r.naturalExposure}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  ) : mod.title === "推荐关注产品" ? (
                    <div className="grid grid-cols-2 gap-4" onClick={(e) => e.stopPropagation()}>
                      <div className="rounded-lg border border-border/60 overflow-hidden">
                        <div className="px-3 py-2 text-xs font-semibold bg-muted/50 flex items-center justify-between">
                          <span>推进（周数据分析）</span>
                          <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" onClick={(e) => { e.stopPropagation(); setLocation('/product-diagnosis'); }}>
                            查看更多
                          </Button>
                        </div>
                        <div className="max-h-[300px] overflow-auto">
                          <table className="w-full text-xs">
                            <thead className="sticky top-0 z-10 bg-background">
                              <tr className="border-b bg-muted/20">
                                <th className="text-left px-3 py-2">产品ID</th>
                                <th className="text-right px-3 py-2">权重评分</th>
                                <th className="text-right px-3 py-2">点击率</th>
                                <th className="text-right px-3 py-2">询盘率</th>
                              </tr>
                            </thead>
                            <tbody>
                              {focusLoading ? (
                                <tr><td className="px-3 py-4 text-muted-foreground" colSpan={4}>加载中...</td></tr>
                              ) : focusPushRows.length === 0 ? (
                                <tr><td className="px-3 py-4 text-muted-foreground" colSpan={4}>暂无推进产品</td></tr>
                              ) : focusPushRows.map((r, idx) => (
                                <tr key={`${r.productId}-push-${idx}`} className="border-b last:border-0">
                                  <td className="px-3 py-2 font-mono">{r.productId || "--"}</td>
                                  <td className="px-3 py-2 text-right font-mono">{r.score}</td>
                                  <td className="px-3 py-2 text-right font-mono">{r.ctr}</td>
                                  <td className="px-3 py-2 text-right font-mono">{r.inquiryRate}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>

                      <div className="rounded-lg border border-border/60 overflow-hidden">
                        <div className="px-3 py-2 text-xs font-semibold bg-muted/50 flex items-center justify-between">
                          <span>新发链接监控（四周≥30）</span>
                          <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" onClick={(e) => { e.stopPropagation(); setLocation('/new-links-analysis'); }}>
                            查看更多
                          </Button>
                        </div>
                        <div className="max-h-[300px] overflow-auto">
                          <table className="w-full text-xs">
                            <thead className="sticky top-0 z-10 bg-background">
                              <tr className="border-b bg-muted/20">
                                <th className="text-left px-3 py-2">产品ID</th>
                                <th className="text-right px-3 py-2">{focusNewCols[0] || "最新数据"}</th>
                                <th className="text-right px-3 py-2">{focusNewCols[1] || "最新第二周"}</th>
                                <th className="text-right px-3 py-2">{focusNewCols[2] || "最新第三周"}</th>
                                <th className="text-right px-3 py-2">{focusNewCols[3] || "最新第四周"}</th>
                              </tr>
                            </thead>
                            <tbody>
                              {focusLoading ? (
                                <tr><td className="px-3 py-4 text-muted-foreground" colSpan={5}>加载中...</td></tr>
                              ) : focusNewRows.length === 0 ? (
                                <tr><td className="px-3 py-4 text-muted-foreground" colSpan={5}>暂无符合条件产品</td></tr>
                              ) : focusNewRows.map((r, idx) => (
                                <tr key={`${String(r?.["产品ID"] || "")}-new-${idx}`} className="border-b last:border-0">
                                  <td className="px-3 py-2 font-mono">{String(r?.["产品ID"] || "--")}</td>
                                  <td className="px-3 py-2 text-right font-mono">{String(r?.[focusNewCols[0]] ?? "--")}</td>
                                  <td className="px-3 py-2 text-right font-mono">{String(r?.[focusNewCols[1]] ?? "--")}</td>
                                  <td className="px-3 py-2 text-right font-mono">{String(r?.[focusNewCols[2]] ?? "--")}</td>
                                  <td className="px-3 py-2 text-right font-mono">{String(r?.[focusNewCols[3]] ?? "--")}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      {mod.links.map((link) => (
                        <Link key={link.href} href={link.href}>
                          <div onClick={(e) => e.stopPropagation()} className="flex items-center justify-between px-3 py-2.5 rounded-lg hover:bg-accent/60 transition-all duration-200 group/link">
                            <div className="flex items-center gap-2.5">
                              <link.icon className="w-4 h-4 text-muted-foreground group-hover/link:text-foreground transition-colors" />
                              <span className="text-sm text-foreground/80 group-hover/link:text-foreground transition-colors">{link.label}</span>
                            </div>
                            <ArrowRight className="w-3.5 h-3.5 text-muted-foreground/40 group-hover/link:text-foreground/60 group-hover/link:translate-x-0.5 transition-all duration-200" />
                          </div>
                        </Link>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </motion.div>
          );
          })}
        </motion.div>

        {/* Feature Highlights */}
        <motion.div className="mt-8" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }}>
          <div className="flex items-center gap-2 mb-5">
            <Zap className="w-4.5 h-4.5 text-muted-foreground/70" />
            <h2 className="text-base font-semibold text-foreground">核心能力</h2>
            <div className="h-px flex-1 bg-border/50 ml-3" />
          </div>
          <div className="grid grid-cols-4 gap-4">
            {features.map((feat, i) => (
              <motion.div key={feat.title} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.6 + i * 0.1 }}>
                <Card className="border-border/40 hover:border-border/70 transition-all duration-300 h-full">
                  <CardContent className="py-5">
                    <div className="w-9 h-9 rounded-lg bg-primary/5 flex items-center justify-center mb-3">
                      <feat.icon className="w-4.5 h-4.5 text-primary/70" />
                    </div>
                    <h3 className="text-sm font-semibold mb-1">{feat.title}</h3>
                    <p className="text-xs text-muted-foreground leading-relaxed">{feat.desc}</p>
                  </CardContent>
                </Card>
              </motion.div>
            ))}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
