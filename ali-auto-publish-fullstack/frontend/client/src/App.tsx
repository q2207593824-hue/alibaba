/**
 * App - 应用根组件
 * 路由配置和全局布局
 *
 * 【如何修改】
 * - 添加新页面 → 在 Route 列表中添加新的 Route 组件，并在上方 import
 * - 修改布局 → 修改 DashboardLayout 组件
 * - 添加全局状态 → 在 ThemeProvider 同级添加新的 Provider
 */
import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { Toaster, toast } from "sonner";
import {
  clearStaleAuthSession,
  configApi,
  getMembershipToken,
  initDesktopBackendConnection,
  isDesktopClient,
  membershipApi,
  prepareAppSessionAfterLogin,
  prepareAppSessionInBackground,
  startCloudAdminConfigWatcher,
} from "@/lib/api";
import { navigateToHome } from "@/lib/navigateHome";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "@/pages/NotFound";
import { Route, Router as WouterRouter, Switch, useLocation } from "wouter";
import { useHashLocation } from "wouter/use-hash-location";
import ErrorBoundary from "./components/ErrorBoundary";
import { ThemeProvider } from "./contexts/ThemeContext";
import { ConfigProvider } from "./contexts/ConfigContext";
import DashboardLayout from "./components/DashboardLayout";
import PageRouteFallback from "./components/PageRouteFallback";
import Dashboard from "./pages/Dashboard";
import MembershipCenter from "./pages/MembershipCenter";
import MembershipLoginDialog from "./components/MembershipLoginDialog";

const ProductUpload = lazy(() => import("./pages/ProductUpload"));
const OptimizeProduct = lazy(() => import("./pages/OptimizeProduct"));
const ImageManager = lazy(() => import("./pages/ImageManager"));
const AiImageGen = lazy(() => import("./pages/AiImageGen"));
const StoreImageCollect = lazy(() => import("./pages/StoreImageCollect"));
const DataDownload = lazy(() => import("./pages/DataDownload"));
const DataAnalysis = lazy(() => import("./pages/DataAnalysis"));
const ProductConfig = lazy(() => import("./pages/ProductConfig"));
const KeywordDownload = lazy(() => import("./pages/KeywordDownload"));
const StoreDataDownload = lazy(() => import("./pages/StoreDataDownload"));
const TrafficChannelDownload = lazy(() => import("./pages/TrafficChannelDownload"));
const ProductOperateDownload = lazy(() => import("./pages/ProductOperateDownload"));
const IndustryKeyword = lazy(() => import("./pages/IndustryKeyword"));
const ProductDiagnosisPage = lazy(() => import("./pages/ProductDiagnosis"));
const SingleProductAnalysisPage = lazy(() => import("./pages/SingleProductAnalysis"));
const TrafficAnalysis = lazy(() => import("./pages/TrafficAnalysis"));
const P4PAnalysis = lazy(() => import("./pages/P4PAnalysis"));
const NewLinksAnalysis = lazy(() => import("./pages/NewLinksAnalysis"));
const TitleOptimizeAnalysis = lazy(() => import("./pages/TitleOptimizeAnalysis"));
const SingleProductChannelData = lazy(() => import("./pages/SingleProductChannelData"));
const VideoBind = lazy(() => import("./pages/VideoBind"));
const PublishPageScanner = lazy(() => import("./pages/PublishPageScanner"));

function Router() {
  const [location, setLocation] = useLocation();
  const [authEpoch, setAuthEpoch] = useState(0);
  const [loginDialogOpen, setLoginDialogOpen] = useState(false);
  const [loginDialogHint, setLoginDialogHint] = useState("");
  const [bootReady, setBootReady] = useState(false);
  const shownKeysRef = useRef<Set<string>>(new Set());
  const lastPathRef = useRef<string>("");
  const sessionHealRef = useRef(false);
  const isAuthed = useMemo(() => {
    void authEpoch;
    return !!getMembershipToken();
  }, [authEpoch]);

  useEffect(() => {
    clearStaleAuthSession();
    setAuthEpoch((n) => n + 1);
    const onAuthChanged = () => setAuthEpoch((n) => n + 1);
    window.addEventListener("membership:auth-changed", onAuthChanged);
    return () => window.removeEventListener("membership:auth-changed", onAuthChanged);
  }, []);
  const token = getMembershipToken();

  useEffect(() => {
    if (isDesktopClient()) {
      void initDesktopBackendConnection();
    }
    // 应用进入后先使用缓存快速放行，再后台补齐最新配置
    const cached = configApi.getCached();
    const bootTimeoutMs = isDesktopClient() ? (cached ? 1500 : 4000) : 8000;
    const bootTimer = window.setTimeout(() => setBootReady(true), bootTimeoutMs);

    const finishBoot = () => {
      window.clearTimeout(bootTimer);
      setBootReady(true);
    };

    if (cached) {
      finishBoot();
      configApi.prime(false).catch(() => undefined);
    } else {
      // 桌面端无缓存时不阻塞首屏：后台拉配置，最多等待 bootTimeoutMs
      const waitReady = !isDesktopClient();
      configApi
        .prime(waitReady)
        .catch(() => undefined)
        .finally(() => finishBoot());
    }

    const ensureDeviceId = (): string => {
      try {
        const key = "client_device_uuid";
        const old = localStorage.getItem(key);
        if (old) return old;
        const uuid = (typeof crypto !== "undefined" && (crypto as any).randomUUID)
          ? (crypto as any).randomUUID()
          : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
        localStorage.setItem(key, uuid);
        return uuid;
      } catch {
        return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
      }
    };

    const reportAgent = async () => {
      try {
        const adminKey = localStorage.getItem("control_admin_key") || localStorage.getItem("membership_admin_key") || "";
        if (!adminKey) return;

        const deviceId = ensureDeviceId();
        const agentId = `agent-${deviceId}`;
        const clientName = "ali-auto-publish-client";
        const appVersion = "web";

        await membershipApi.adminAgentRegister(
          {
            agent_id: agentId,
            client_name: clientName,
            machine_id: deviceId,
            app_version: appVersion,
          },
          adminKey
        );

        await membershipApi.adminAgentHeartbeat(
          {
            agent_id: agentId,
            status: "active",
          },
          adminKey
        );
      } catch {
        // ignore
      }
    };

    reportAgent();
    const timer = window.setInterval(reportAgent, 60 * 1000);
    return () => {
      window.clearTimeout(bootTimer);
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!token) return;
    void prepareAppSessionInBackground();
  }, [token]);

  useEffect(() => {
    const watch = !!(token && isDesktopClient() && bootReady);
    startCloudAdminConfigWatcher(watch);
    return () => startCloudAdminConfigWatcher(false);
  }, [token, bootReady]);

  useEffect(() => {
    const onMembershipRequired = async (evt: Event) => {
      const e = evt as CustomEvent<any>;
      const reason = String(e?.detail?.reason || "").trim();
      const path = String(e?.detail?.path || location || "").trim();
      const rawDetail = String(e?.detail?.raw_detail || "").trim();

      const message = (() => {
        if (reason === "store_not_bound") return "当前账户未绑定店铺，请先绑定店铺";
        if (reason === "auth_expired") return "登录已过期，请重新登录会员中心";
        if (reason === "session_invalid") return "当前设备会话无效，请在本机重新登录会员中心";
        if (reason === "not_member") return "试用期已过且非会员，请先充值或兑换会员";
        return rawDetail || "当前账户无访问权限，请联系管理员";
      })();

      // 同一页面、同一原因只提示一次；换页面后可再次提示
      const onceKey = `${path}::${reason || "forbidden"}`;
      if (shownKeysRef.current.has(onceKey)) return;
      shownKeysRef.current.add(onceKey);

      const actionLabel = reason === "store_not_bound" ? "去绑定店铺" : "去会员中心";

      const openLogin =
        reason === "auth_expired" ||
        reason === "session_invalid" ||
        reason === "missing_authorization" ||
        reason === "auth_invalid";

      if (openLogin && getMembershipToken() && !sessionHealRef.current) {
        sessionHealRef.current = true;
        const healed = await prepareAppSessionAfterLogin().catch(() => false);
        sessionHealRef.current = false;
        if (healed) {
          toast.success("会员会话已同步到本地，请重试当前操作");
          return;
        }
      }

      toast.warning(message, {
        description: rawDetail && rawDetail !== message ? `后端返回：${rawDetail}` : undefined,
        action: {
          label: openLogin ? "立即登录" : actionLabel,
          onClick: () => {
            if (openLogin) {
              setLoginDialogHint(message);
              setLoginDialogOpen(true);
              return;
            }
            setLocation("/membership");
          },
        },
      });

      if (openLogin) {
        setLoginDialogHint(message);
        setLoginDialogOpen(true);
      }
    };
    window.addEventListener("membership:required", onMembershipRequired as EventListener);
    return () => window.removeEventListener("membership:required", onMembershipRequired as EventListener);
  }, [setLocation, location]);

  useEffect(() => {
    // 换页面后允许该页面再次提示一次
    if (lastPathRef.current !== location) {
      lastPathRef.current = location;
    }

    if (!isAuthed && location !== "/membership") {
      setLocation("/membership");
    }
  }, [isAuthed, location, setLocation]);

  if (!isAuthed) {
    return (
      <>
        <Switch>
          <Route path="/membership" component={MembershipCenter} />
          <Route component={MembershipCenter} />
        </Switch>
        <MembershipLoginDialog
          open={loginDialogOpen}
          onOpenChange={setLoginDialogOpen}
          description={loginDialogHint || undefined}
          onSuccess={() => {
            setAuthEpoch((n) => n + 1);
            navigateToHome(setLocation);
            void prepareAppSessionAfterLogin({ background: true }).then((synced) => {
              if (!synced) {
                toast.warning("本地后端未同步会话，请确认 backend 已启动");
              }
            });
          }}
        />
      </>
    );
  }

  if (!bootReady && location !== "/membership") {
    return (
      <div className="h-screen w-full flex items-center justify-center bg-background text-muted-foreground text-sm">
        正在加载系统配置，请稍候...
      </div>
    );
  }

  return (
    <>
    <DashboardLayout>
      <Suspense fallback={<PageRouteFallback />}>
      <Switch>
        <Route path="/membership" component={MembershipCenter} />
        <Route path="/" component={Dashboard} />
        <Route path="/product-upload" component={ProductUpload} />
        <Route path="/optimize-product" component={OptimizeProduct} />
        <Route path="/video-bind" component={VideoBind} />
        <Route path="/publish-page-scanner" component={PublishPageScanner} />
        <Route path="/product-config" component={ProductConfig} />
        <Route path="/image-manager" component={ImageManager} />
        <Route path="/ai-image-gen" component={AiImageGen} />
        <Route path="/store-image-collect" component={StoreImageCollect} />
        <Route path="/data-download" component={DataDownload} />
        <Route path="/product-operate-download" component={ProductOperateDownload} />
        <Route path="/keyword-download" component={KeywordDownload} />
        <Route path="/industry-keyword" component={IndustryKeyword} />
        <Route path="/store-data" component={StoreDataDownload} />
        <Route path="/traffic-channel-download" component={TrafficChannelDownload} />
        <Route path="/data-analysis" component={DataAnalysis} />
        <Route path="/product-diagnosis" component={ProductDiagnosisPage} />
        <Route path="/single-product-analysis" component={SingleProductAnalysisPage} />
        <Route path="/traffic-analysis" component={TrafficAnalysis} />
        <Route path="/single-product-channel" component={SingleProductChannelData} />
        <Route path="/p4p-analysis" component={P4PAnalysis} />
        <Route path="/new-links-analysis" component={NewLinksAnalysis} />
        <Route path="/title-optimize-analysis" component={TitleOptimizeAnalysis} />
        <Route path="/membership" component={MembershipCenter} />
        <Route path="/404" component={NotFound} />
        <Route component={NotFound} />
      </Switch>
      </Suspense>
    </DashboardLayout>
    <MembershipLoginDialog
      open={loginDialogOpen}
      onOpenChange={setLoginDialogOpen}
      description={loginDialogHint || undefined}
      onSuccess={() => {
        setAuthEpoch((n) => n + 1);
        void prepareAppSessionAfterLogin().then((synced) => {
          navigateToHome(setLocation);
          if (!synced) {
            toast.warning("本地后端未同步会话，请确认 backend 已启动");
          }
        });
      }}
    />
    </>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider defaultTheme="light">
        <ConfigProvider>
          <TooltipProvider>
            <Toaster position="top-right" richColors closeButton />
            <WouterRouter hook={useHashLocation}>
              <Router />
            </WouterRouter>
          </TooltipProvider>
        </ConfigProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}

export default App;
