import { useEffect, useMemo, useState } from "react";
import QRCode from "qrcode";
import { useLocation } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import {
  configApi,
  clearStaleAuthSession,
  ensureDesktopBackendForLogin,
  getMembershipToken,
  isDesktopClient,
  membershipApi,
  notifyAuthChanged,
  prepareAppSessionAfterLogin,
  setMembershipToken,
} from "@/lib/api";
import { performMembershipLogin } from "@/components/MembershipLoginDialog";
import { navigateToHome } from "@/lib/navigateHome";

const ADMIN_KEY_STORE = "membership_admin_key";
const CONTROL_ADMIN_KEY_STORE = "control_admin_key";
const STORE_PROFILE_CACHE_KEY = "membership_store_profile_cache";
const ME_CACHE_KEY = "membership_me_cache_v1";

function readMeCache(): any | null {
  try {
    const raw = localStorage.getItem(ME_CACHE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeMeCache(data: any) {
  try {
    if (data && typeof data === "object") {
      localStorage.setItem(ME_CACHE_KEY, JSON.stringify(data));
    }
  } catch {
    // ignore
  }
}

function getStoreProfileCacheKey(username?: string) {
  const u = String(username || "").trim();
  return u ? `${STORE_PROFILE_CACHE_KEY}:${u}` : STORE_PROFILE_CACHE_KEY;
}

export default function MembershipCenter() {
  const [, setLocation] = useLocation();

  // auth forms
  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [registerUsername, setRegisterUsername] = useState("");
  const [registerPassword, setRegisterPassword] = useState("");
  const [registerInviteCode, setRegisterInviteCode] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);
  const [enteringApp, setEnteringApp] = useState(false);

  // user area
  const [me, setMe] = useState<any>(() => readMeCache());
  const [loadingMe, setLoadingMe] = useState(() => !!getMembershipToken() && !readMeCache());
  const [loadMeError, setLoadMeError] = useState<string | null>(null);
  const [ledger, setLedger] = useState<any[]>([]);
  const [amount, setAmount] = useState(1500);
  const [withdrawPoints, setWithdrawPoints] = useState<number | "">("");
  const [withdrawAccount, setWithdrawAccount] = useState("");
  const [withdrawErrors, setWithdrawErrors] = useState<{ points?: string; account?: string }>({});
  const [orders, setOrders] = useState<any[]>([]);
  const [lastOrderNo, setLastOrderNo] = useState("");
  const [paymentInfo, setPaymentInfo] = useState<any>(null);
  const [paymentDialogOpen, setPaymentDialogOpen] = useState(false);
  const [rechargeCenterOpen, setRechargeCenterOpen] = useState(false);
  const [withdrawDialogOpen, setWithdrawDialogOpen] = useState(false);
  const [paymentStatus, setPaymentStatus] = useState("pending");
  const [polling, setPolling] = useState(false);
  const [wechatQrDataUrl, setWechatQrDataUrl] = useState("");
  const [alipayQrDataUrl, setAlipayQrDataUrl] = useState("");
  const [showFloatRecharge, setShowFloatRecharge] = useState(true);

  // admin area
  const [adminKey, setAdminKey] = useState(() => localStorage.getItem(ADMIN_KEY_STORE) || "");
  const [adminConsoleLoggedIn, setAdminConsoleLoggedIn] = useState(() => localStorage.getItem("admin_console_logged_in") === "1");
  const [adminConsoleUser, setAdminConsoleUser] = useState(() => localStorage.getItem("admin_console_user") || "admin");
  const [adminUsers, setAdminUsers] = useState<any[]>([]);
  const [adminAgents, setAdminAgents] = useState<any[]>([]);
  const [adminKeywordReports, setAdminKeywordReports] = useState<any[]>([]);
  const [selectedKeywordReportIds, setSelectedKeywordReportIds] = useState<number[]>([]);
  const [adminWithdraws, setAdminWithdraws] = useState<any[]>([]);
  const [adminDashboard, setAdminDashboard] = useState<any>(null);
  const [keywordDetailOpen, setKeywordDetailOpen] = useState(false);
  const [keywordDetailLoading, setKeywordDetailLoading] = useState(false);
  const [keywordDetail, setKeywordDetail] = useState<any>(null);
  const [memberDetailOpen, setMemberDetailOpen] = useState(false);
  const [selectedMember, setSelectedMember] = useState<any>(null);
  const [selectedCompanyUsers, setSelectedCompanyUsers] = useState<any[]>([]);
  const [withdrawDetailOpen, setWithdrawDetailOpen] = useState(false);
  const [selectedWithdraw, setSelectedWithdraw] = useState<any>(null);
  const [bindingStore, setBindingStore] = useState(false);
  const [memberForm, setMemberForm] = useState<any>({
    mode: "normal",
    note: "",
    points_balance: "",
    trial_start_at: "",
    trial_end_at: "",
    vip_expire_at: "",
    password: "",
  });

  const token = getMembershipToken();
  const loginBgUrl = useMemo(() => {
    try {
      const items = import.meta.glob("@/assets/*.{png,jpg,jpeg,webp,avif}", {
        eager: true,
        query: "?url",
        import: "default",
      }) as Record<string, string>;
      const urls = Object.values(items).filter(Boolean);
      if (!urls.length) return "";
      const idx = Math.floor(Math.random() * urls.length);
      return urls[idx] || "";
    } catch {
      return "";
    }
  }, []);

  const isCompanyVerifiedMember = useMemo(() => {
    // 统一按“公司 + 会员有效期(试用/VIP)”判定颜色
    const company = String(me?.company_name || "").trim();
    const vipExpire = String(me?.vip_expire_at || "").trim();
    const trialEnd = String(me?.trial_end_at || "").trim();

    let vipValid = false;
    let trialValid = false;

    if (vipExpire) {
      const dt = new Date(vipExpire.replace(" ", "T"));
      if (!Number.isNaN(dt.getTime())) {
        vipValid = dt.getTime() > Date.now();
      }
    }

    if (trialEnd) {
      const dt = new Date(trialEnd.replace(" ", "T"));
      if (!Number.isNaN(dt.getTime())) {
        trialValid = dt.getTime() > Date.now();
      }
    }

    return !!company && (vipValid || trialValid);
  }, [me]);

  const loadMe = async () => {
    if (localStorage.getItem("admin_console_logged_in") === "1" && localStorage.getItem(ADMIN_KEY_STORE)) {
      setMe(null);
      setLoadingMe(false);
      setLoadMeError(null);
      return;
    }
    if (!getMembershipToken()) {
      setMe(null);
      setLoadingMe(false);
      setLoadMeError(null);
      return;
    }
    try {
      if (!readMeCache()) setLoadingMe(true);
      setLoadMeError(null);
      const res = await membershipApi.me();
      const data = res?.data || res;

      // 用本地缓存的店铺资料补齐展示，避免云端 me 暂未同步时显示 "-"
      let merged = data || null;
      try {
        const cacheRaw = localStorage.getItem(getStoreProfileCacheKey((data as any)?.username)) || "";
        const cache = cacheRaw ? JSON.parse(cacheRaw) : null;
        if (merged && cache && typeof cache === "object") {
          merged = {
            ...merged,
            company_name: String(merged.company_name || cache.company_name || "").trim(),
            main_category: String(merged.main_category || cache.main_category || "").trim(),
            is_verified: String(merged.is_verified || cache.is_verified || "").trim(),
            service_years: String(merged.service_years || cache.service_years || "").trim(),
            page_level_star: String(merged.page_level_star || cache.page_level_star || "").trim(),
          };
        }
      } catch {
        // ignore cache parse error
      }

      setMe(merged || null);
      if (merged) writeMeCache(merged);
    } catch (e: any) {
      const status = Number(e?.response?.status || 0);
      const msg = String(e?.message || "");
      const authFailed =
        status === 401 ||
        status === 403 ||
        /登录已失效|登录已过期|请重新登录|会话校验失败|设备校验失败/i.test(msg);
      if (authFailed) {
        setMe(null);
        setMembershipToken("");
        setLoadMeError(null);
      } else {
        setLoadMeError(msg || "无法加载会员信息，请检查网络后重试");
      }
    } finally {
      setLoadingMe(false);
    }
  };

  const loadLedger = async () => {
    try {
      const res = await membershipApi.ledger(50);
      const data = res?.data || res;
      setLedger(Array.isArray(data) ? data : []);
    } catch {
      setLedger([]);
    }
  };

  const loadOrders = async () => {
    try {
      const res = await membershipApi.listRechargeOrdersPaged({ page: 1, page_size: 20 });
      const data = res?.data || res;
      setOrders(Array.isArray(data?.items) ? data.items : []);
    } catch {
      setOrders([]);
    }
  };

  const loadAdminSummary = async (keyOverride?: string) => {
    const effectiveKey = String(keyOverride || adminKey || "").trim();
    if (!effectiveKey) return;
    try {
      const [w, d] = await Promise.all([
        membershipApi.adminListWithdraw({ limit: 500, adminKey: effectiveKey }),
        membershipApi.adminDashboard(30, effectiveKey),
      ]);
      setAdminWithdraws(Array.isArray((w as any)?.data || w) ? ((w as any)?.data || w) : []);
      setAdminDashboard((d as any)?.data || d || null);
    } catch (e: any) {
      const status = Number(e?.response?.status || 0);
      const msg = String(e?.message || e?.response?.data?.detail || "");
      if (status === 401 || status === 403 || /管理员权限|admin.*key|密钥/i.test(msg)) {
        toast.error("管理员数据加载失败：管理密钥无效或未与云端同步，请退出后重新登录");
      }
    }
  };

  const loadAdminUsersList = async (keyOverride?: string) => {
    const effectiveKey = String(keyOverride || adminKey || "").trim();
    if (!effectiveKey) return;
    try {
      const u = await membershipApi.adminUsers({ adminKey: effectiveKey, limit: 200 });
      setAdminUsers(Array.isArray((u as any)?.data || u) ? ((u as any)?.data || u) : []);
    } catch {
      // keep existing list
    }
  };

  const loadAdminAgentsList = async (keyOverride?: string) => {
    const effectiveKey = String(keyOverride || adminKey || "").trim();
    if (!effectiveKey) return;
    try {
      const a = await membershipApi.adminAgents({ adminKey: effectiveKey, limit: 200 });
      setAdminAgents(Array.isArray((a as any)?.data || a) ? ((a as any)?.data || a) : []);
    } catch {
      // keep existing list
    }
  };

  const loadAdminKeywordsList = async (keyOverride?: string) => {
    const effectiveKey = String(keyOverride || adminKey || "").trim();
    if (!effectiveKey) return;
    try {
      const k = await membershipApi.adminTelemetryKeywords({ adminKey: effectiveKey, limit: 200 });
      const keywordReports = Array.isArray((k as any)?.data || k) ? ((k as any)?.data || k) : [];
      setAdminKeywordReports(keywordReports);
      setSelectedKeywordReportIds((prev) => {
        const valid = new Set<number>(keywordReports.map((x: any) => Number(x?.id || 0)).filter((x: number) => x > 0));
        return prev.filter((id) => valid.has(id));
      });
    } catch {
      // keep existing list
    }
  };

  const loadAdminData = async (keyOverride?: string) => {
    const effectiveKey = String(keyOverride || adminKey || "").trim();
    if (!effectiveKey) return;
    try {
      await loadAdminSummary(effectiveKey);
      await Promise.all([
        loadAdminUsersList(effectiveKey),
        loadAdminAgentsList(effectiveKey),
        loadAdminKeywordsList(effectiveKey),
      ]);
    } catch (e: any) {
      const msg = String(e?.message || e?.response?.data?.detail || "");
      toast.error(msg || "管理员数据加载失败，请检查云端网络");
    }
  };

  const refreshAdminKeyFromBackend = async (): Promise<string> => {
    if (!adminConsoleLoggedIn || !getMembershipToken()) return adminKey;
    try {
      const res: any = await membershipApi.refreshAdminSessionKey();
      const payload = res?.data ?? res;
      const data = payload?.data ?? payload;
      const nextKey = String(data?.admin_key || "").trim();
      if (!nextKey || nextKey === "change-me-admin") return adminKey;
      if (nextKey !== adminKey) {
        localStorage.setItem(ADMIN_KEY_STORE, nextKey);
        localStorage.setItem(CONTROL_ADMIN_KEY_STORE, nextKey);
        setAdminKey(nextKey);
      }
      return nextKey;
    } catch {
      return adminKey;
    }
  };

  useEffect(() => {
    loadMe();
  }, []);

  useEffect(() => {
    if (token) {
      const t = window.setTimeout(() => {
        loadLedger();
        loadOrders();
      }, 400);
      return () => window.clearTimeout(t);
    }
  }, [token]);

  useEffect(() => {
    if (!adminConsoleLoggedIn) return;
    void (async () => {
      const key = await refreshAdminKeyFromBackend();
      const effectiveKey = key || adminKey;
      await loadAdminSummary(effectiveKey);
      window.setTimeout(() => {
        void loadAdminUsersList(effectiveKey);
        void loadAdminAgentsList(effectiveKey);
        void loadAdminKeywordsList(effectiveKey);
      }, 50);
    })();
  }, [adminConsoleLoggedIn, adminKey]);

  useEffect(() => {
    if (!(adminConsoleLoggedIn && !!adminKey)) return;
    const t = window.setInterval(() => {
      void loadAdminSummary();
    }, 60000);
    return () => window.clearInterval(t);
  }, [adminConsoleLoggedIn, adminKey]);

  const handleLogin = async () => {
    if (loginLoading) return;

    const username = String(loginUsername || "").trim();
    const password = String(loginPassword || "").trim();
    if (!username || !password) {
      toast.warning("请输入账号和密码");
      return;
    }

    setLoginLoading(true);
    try {
      if (isDesktopClient()) {
        toast.info("正在启动本地服务，请稍候…", { duration: 4000 });
        await ensureDesktopBackendForLogin(30000);
      }
      const kind = await performMembershipLogin(username, password);
      if (kind === "admin") {
        setMe(null);
        setAdminConsoleLoggedIn(true);
        setAdminConsoleUser(localStorage.getItem("admin_console_user") || username);
        setAdminKey(localStorage.getItem(ADMIN_KEY_STORE) || "");
        toast.success("已自动识别管理员账号并登录");
        await loadAdminData();
        navigateToHome(setLocation);
        void prepareAppSessionAfterLogin({ background: true });
        return;
      }

      setAdminConsoleLoggedIn(false);
      setAdminKey("");
      toast.success("登录成功，正在进入系统…");
      navigateToHome(setLocation);
      void prepareAppSessionAfterLogin({ background: true }).then((synced) => {
        if (!synced) {
          toast.warning("本地后端未同步会话，请确认已启动 backend；部分功能可能需稍后重试");
        }
        void Promise.all([loadMe(), loadLedger(), loadOrders()]);
      });
    } catch (e: any) {
      toast.error(e?.message || "登录失败");
    } finally {
      setLoginLoading(false);
    }
  };


  const handleRegister = async () => {
    try {
      await membershipApi.register({
        username: registerUsername,
        password: registerPassword,
        invite_code: registerInviteCode || null,
      });
      // 注册后直接登录
      const loginRes = await membershipApi.login({ username: registerUsername, password: registerPassword });
      const loginData = (loginRes as any)?.data || loginRes;
      const t = loginData?.token || "";
      if (!t) throw new Error("注册成功但自动登录失败");
      try {
        localStorage.removeItem(STORE_PROFILE_CACHE_KEY);
      } catch {
        // ignore
      }
      setMembershipToken(t);
      // [性能优化] 将串行请求改为并行，大幅缩短阻塞时间
      await Promise.all([loadMe(), loadLedger(), loadOrders()]);
      toast.success("注册成功，已自动登录");
      setLocation("/");
    } catch (e: any) {
      toast.error(e?.message || "注册失败");
    }
  };

  const buildWechatQr = async (content?: string) => {
    try {
      if (!content) {
        setWechatQrDataUrl("");
        return;
      }
      const url = await QRCode.toDataURL(content, { width: 220, margin: 1 });
      setWechatQrDataUrl(url);
    } catch {
      setWechatQrDataUrl("");
    }
  };

  const buildAlipayQr = async (content?: string) => {
    try {
      if (!content) {
        setAlipayQrDataUrl("");
        return;
      }
      const url = await QRCode.toDataURL(content, { width: 220, margin: 1 });
      setAlipayQrDataUrl(url);
    } catch {
      setAlipayQrDataUrl("");
    }
  };

  const handleRecharge = async (channel: "wechat" | "alipay") => {
    if (adminConsoleLoggedIn) {
      toast.warning("管理员账户不支持充值，请使用普通会员账户进行充值");
      return;
    }
    try {
      const res = await membershipApi.createRecharge({ channel, amount_yuan: amount });
      const data = (res as any)?.data || res;
      setLastOrderNo(data?.order_no || "");
      setPaymentInfo(data?.payment || null);

      if (channel === "wechat") {
        await buildWechatQr(String(data?.payment?.qr_content || "").trim());
        setAlipayQrDataUrl("");
      } else {
        await buildAlipayQr(String(data?.payment?.pay_url || data?.payment?.qr_content || "").trim());
        setWechatQrDataUrl("");
      }

      setPaymentStatus("pending");
      setPaymentDialogOpen(true);
      toast.success(`已创建订单 ${data?.order_no || ""}`);
      await loadOrders();
    } catch (e: any) {
      toast.error(e?.message || "创建充值失败");
    }
  };

  const handleMockPaid = async () => {
    if (!lastOrderNo) {
      toast.warning("请先创建充值订单");
      return;
    }
    try {
      await membershipApi.mockPaid(lastOrderNo);
      toast.success("已模拟支付成功并入账");
      setPaymentStatus("paid");
      await loadMe();
      await loadLedger();
      await loadOrders();
    } catch (e: any) {
      toast.error(e?.message || "模拟支付失败");
    }
  };

  const handleCheckOrder = async (silent = false) => {
    if (adminConsoleLoggedIn) {
      if (!silent) toast.warning("管理员账户无会员订单，请切换普通会员账号查询");
      return "unknown";
    }
    if (!lastOrderNo) {
      if (!silent) toast.warning("请先输入订单号");
      return "unknown";
    }
    try {
      const res = await membershipApi.getRechargeOrder(lastOrderNo);
      const data = (res as any)?.data || res;
      const status = String(data?.status || "unknown");
      setPaymentStatus(status);
      if (!silent) toast.info(`订单状态：${status}`);
      if (status === "paid") {
        await loadMe();
        await loadLedger();
        await loadOrders();
      }
      return status;
    } catch (e: any) {
      if (!silent) toast.error(e?.message || "查询订单失败");
      return "unknown";
    }
  };

  const pollOrderStatus = async () => {
    if (!lastOrderNo) return;
    setPolling(true);
    try {
      for (let i = 0; i < 8; i++) {
        const status = await handleCheckOrder(true);
        if (status === "paid") {
          toast.success("支付已完成");
          return;
        }
        await new Promise((r) => setTimeout(r, 1500));
      }
      toast.info("仍未支付成功，请稍后再查");
    } finally {
      setPolling(false);
    }
  };

  const handleRedeem = async () => {
    try {
      await membershipApi.redeemVip(1);
      toast.success("兑换成功");
      await loadMe();
      await loadLedger();
    } catch (e: any) {
      toast.error(e?.message || "兑换失败");
    }
  };

  const handleWithdraw = async (): Promise<boolean> => {
    const points = Number(withdrawPoints || 0);
    const account = String(withdrawAccount || "").trim();

    const errs: { points?: string; account?: string } = {};
    if (!points || points <= 0) errs.points = "此为必填项";
    if (!account) errs.account = "此为必填项";
    setWithdrawErrors(errs);

    if (Object.keys(errs).length > 0) {
      toast.warning("请完善必填项后再提交");
      return false;
    }

    try {
      await membershipApi.applyWithdraw({ points, channel: "alipay", account });
      toast.success("提交成功");
      setWithdrawErrors({});
      await loadLedger();
      if (showAdminTabs) {
        await loadAdminData();
      }
      return true;
    } catch (e: any) {
      toast.error(e?.message || "提现失败");
      return false;
    }
  };

  const approveWithdraw = async (withdrawNo: string) => {
    try {
      await membershipApi.adminApproveWithdraw(withdrawNo, adminKey);
      toast.success(`已通过：${withdrawNo}`);
      await loadAdminData();
    } catch (e: any) {
      toast.error(e?.message || "审批失败");
    }
  };

  const rejectWithdraw = async (withdrawNo: string) => {
    const reason = window.prompt("请输入驳回原因", "资料不完整") || "";
    if (!reason.trim()) return;
    try {
      await membershipApi.adminRejectWithdraw(withdrawNo, reason.trim(), adminKey);
      toast.success(`已驳回：${withdrawNo}`);
      await loadAdminData();
    } catch (e: any) {
      toast.error(e?.message || "驳回失败");
    }
  };

  const handleLogout = () => {
    setMembershipToken("");
    localStorage.removeItem("admin_console_logged_in");
    localStorage.removeItem("admin_console_user");
    localStorage.removeItem(ADMIN_KEY_STORE);
    localStorage.removeItem(CONTROL_ADMIN_KEY_STORE);
    // 兼容历史缓存键
    localStorage.removeItem(STORE_PROFILE_CACHE_KEY);
    setMe(null);
    setAdminConsoleLoggedIn(false);
    setAdminKey("");
    clearStaleAuthSession();
    notifyAuthChanged();
    toast.success("已退出登录");
  };

  const openMemberDetail = (u: any) => {
    const company = String(u?.company_name || "").trim() || "未绑定公司";
    const companyUsers = (adminUsers || []).filter((x: any) => (String(x?.company_name || "").trim() || "未绑定公司") === company);
    setSelectedCompanyUsers(companyUsers);

    setSelectedMember(u);
    setMemberForm({
      mode: String(u?.control_mode || "normal"),
      note: String(u?.control_note || ""),
      points_balance: u?.points_balance != null ? String(u.points_balance) : "",
      trial_start_at: String(u?.trial_start_at || ""),
      trial_end_at: String(u?.trial_end_at || ""),
      vip_expire_at: String(u?.vip_expire_at || ""),
      password: "",
    });
    setMemberDetailOpen(true);
  };

  const saveMemberDetail = async () => {
    if (!selectedMember?.id) return;
    try {
      await membershipApi.adminUserControl({
        user_id: Number(selectedMember.id),
        mode: (memberForm.mode || "normal") as any,
        note: memberForm.note || "",
        adminKey,
      });
      await membershipApi.adminUserUpdate({
        user_id: Number(selectedMember.id),
        password: (memberForm.password || "").trim() || undefined,
        points_balance: Number(memberForm.points_balance || 0),
        trial_start_at: (memberForm.trial_start_at || "").trim() || undefined,
        trial_end_at: (memberForm.trial_end_at || "").trim() || undefined,
        vip_expire_at: (memberForm.vip_expire_at || "").trim() || undefined,
        adminKey,
      });
      toast.success("会员信息已更新");
      setMemberDetailOpen(false);
      await loadAdminData();
    } catch (e: any) {
      toast.error(e?.message || "保存失败");
    }
  };

  const deleteMemberInDetail = async () => {
    if (!selectedMember?.id) return;
    const uid = Number(selectedMember.id);
    const uname = String(selectedMember.username || "");
    if (!window.confirm(`确认删除会员 ${uname}（ID: ${uid}）？此操作不可恢复`)) return;
    try {
      await membershipApi.adminUserDelete({ user_id: uid, adminKey });
      toast.success(`已删除会员 ${uname}`);
      setMemberDetailOpen(false);
      setSelectedMember(null);
      await loadAdminData();
    } catch (e: any) {
      toast.error(e?.message || "删除会员失败");
    }
  };

  const openKeywordDetail = async (reportId: number) => {
    if (!adminKey) {
      toast.warning("请先管理员登录");
      return;
    }
    try {
      setKeywordDetailOpen(true);
      setKeywordDetailLoading(true);
      const res = await membershipApi.adminTelemetryKeywordDetail({ report_id: reportId, limit: 2000, adminKey });
      const data = (res as any)?.data || res;
      setKeywordDetail(data || null);
    } catch (e: any) {
      toast.error(e?.message || "加载关键词明细失败");
      setKeywordDetail(null);
    } finally {
      setKeywordDetailLoading(false);
    }
  };

  const toggleKeywordReport = (reportId: number, checked: boolean) => {
    const rid = Number(reportId || 0);
    if (rid <= 0) return;
    setSelectedKeywordReportIds((prev) => {
      if (checked) return prev.includes(rid) ? prev : [...prev, rid];
      return prev.filter((x) => x !== rid);
    });
  };

  const deleteSelectedKeywordReports = async () => {
    const ids = Array.from(new Set(selectedKeywordReportIds)).filter((x) => Number(x) > 0);
    if (!ids.length) {
      toast.warning("请先选择要删除的回传记录");
      return;
    }
    if (!window.confirm(`确认删除选中的 ${ids.length} 条关键词回传记录吗？`)) return;
    try {
      await membershipApi.adminDeleteTelemetryKeywords({ report_ids: ids, adminKey });
      toast.success(`已删除 ${ids.length} 条回传记录`);
      setSelectedKeywordReportIds([]);
      await loadAdminData();
    } catch (e: any) {
      toast.error(e?.message || "删除失败");
    }
  };

  const handleBindStore = async () => {
    if (bindingStore) return;

    try {
      setBindingStore(true);
      if (isDesktopClient()) {
        toast.info("正在启动本地服务…", { duration: 3000 });
        await ensureDesktopBackendForLogin(20000);
      }
      toast.info("正在打开登录浏览器，请在弹出的窗口完成登录...");

      const result = await configApi.loginCookieByBrowserManager();
      const payload = result?.data || result;
      const count = Number(payload?.data?.count ?? payload?.count ?? 0);
      const profile = payload?.data?.profile || payload?.profile || {};

      const companyName = String(profile?.company_name || "").trim();
      const mainCategory = String(profile?.main_category || "").trim();

      // 先用绑定接口返回的资料即时回显，并写入缓存，避免云端 me 暂未同步时页面仍显示 "-"
      if (companyName || mainCategory) {
        const mergedProfile = {
          company_name: companyName,
          main_category: mainCategory,
          is_verified: String(profile?.is_verified || ""),
          service_years: String(profile?.service_years || ""),
          page_level_star: String(profile?.page_level_star || ""),
        };
        try {
          const cacheKey = getStoreProfileCacheKey(me?.username || loginUsername || registerUsername);
          localStorage.setItem(cacheKey, JSON.stringify(mergedProfile));
        } catch {
          // ignore
        }

        setMe((prev: any) => ({
          ...(prev || {}),
          ...mergedProfile,
        }));
      }

      void loadMe();
      // 清除本地配置缓存，强制重新从后端加载最新配置（含刚写入的分组发品链接）
      // 注意：不能用 configApi.reset()，那会把整个配置重置为默认值，导致刚写入的分组数据丢失
      configApi.invalidateCache();
      await configApi.get(true);
      
      if (showAdminTabs) {
        void loadAdminData();
      }

      if (!companyName && !mainCategory) {
        toast.warning(`已保存 Cookie（${count} 条），但暂未采集到店铺信息，请确认已登录到店铺后台后重试`);
      } else {
        toast.success(`店铺绑定成功：${companyName || "-"} / ${mainCategory || "-"}`);
      }
    } catch (e: any) {
      // 透出后端 detail/message，便于客户与客服定位失败环节（驱动、登录超时、网络等）
      toast.error(e?.message || "店铺绑定失败");
    } finally {
      setBindingStore(false);
    }
  };

  const showAdminTabs = useMemo(() => adminConsoleLoggedIn && !!adminKey, [adminConsoleLoggedIn, adminKey]);

  const adminCompanyGroups = useMemo(() => {
    const map = new Map<string, any[]>();
    const unboundUsers: any[] = [];

    for (const u of adminUsers || []) {
      const company = String(u?.company_name || "").trim();
      if (!company) {
        unboundUsers.push(u);
        continue;
      }
      const arr = map.get(company) || [];
      arr.push(u);
      map.set(company, arr);
    }

    const boundGroups = Array.from(map.entries())
      .map(([company, users]) => ({
        company,
        users: [...users].sort((a: any, b: any) => Number(b?.online || 0) - Number(a?.online || 0)),
      }))
      .sort((a, b) => {
        const aOnline = a.users.some((x: any) => Number(x?.online || 0) === 1) ? 1 : 0;
        const bOnline = b.users.some((x: any) => Number(x?.online || 0) === 1) ? 1 : 0;
        return bOnline - aOnline;
      });

    const unboundSorted = [...unboundUsers].sort((a: any, b: any) => Number(b?.online || 0) - Number(a?.online || 0));

    return { boundGroups, unboundUsers: unboundSorted };
  }, [adminUsers]);

  const openRechargeByFloat = () => {
    setRechargeCenterOpen(true);
  };

  const enterSystem = async () => {
    if (enteringApp) return;
    setEnteringApp(true);
    try {
      navigateToHome(setLocation);
      void prepareAppSessionAfterLogin({ background: true }).then((synced) => {
        if (!synced) {
          toast.warning("本地后端未同步会话，请确认 backend 已运行；已进入系统，部分功能可能需稍后重试");
        }
      });
    } finally {
      setEnteringApp(false);
    }
  };

  const isAdminSession = adminConsoleLoggedIn && !!adminKey;
  const displayMe = isAdminSession
    ? { username: adminConsoleUser || "admin", is_admin: true }
    : me;

  // 未登录：立即显示登录/注册（不等待 loadMe）
  if (loadMeError && token && !isAdminSession) {
    return (
      <div className="p-8 max-w-lg space-y-4">
        <p className="text-sm text-destructive">{loadMeError}</p>
        <p className="text-xs text-muted-foreground">
          软件会自动切换网络线路重试。若多次失败，请检查网络连接后重启本程序。
        </p>
        <div className="flex gap-2">
          <Button onClick={() => void loadMe()}>重试</Button>
          <Button
            variant="outline"
            onClick={() => {
              setMembershipToken("");
              setLoadMeError(null);
              void loadMe();
            }}
          >
            重新登录
          </Button>
        </div>
      </div>
    );
  }

  // 未登录：只显示登录/注册
  if (!displayMe && !isAdminSession) {
    if (loadingMe && token) {
      return (
        <div className="h-screen flex items-center justify-center text-sm text-muted-foreground">
          正在加载会员信息…
        </div>
      );
    }
    return (
      <div className="h-screen relative overflow-hidden">
        <div
          className="absolute inset-0 bg-cover bg-center bg-no-repeat"
          style={{ backgroundImage: `url(${loginBgUrl})` }}
        />
        <div className="absolute inset-0 bg-slate-900/55" />

        <div className="relative z-10 h-screen flex items-center justify-center p-6">
          <Card className="w-full max-w-md border-white/30 bg-white/10 backdrop-blur-md shadow-2xl rounded-3xl text-white">
            <CardHeader className="pb-1 text-center">
              <CardTitle className="text-4xl font-extrabold tracking-wide">会员中心</CardTitle>

            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label className="text-slate-100">账号</Label>
                <Input
                  value={loginUsername}
                  onChange={(e) => setLoginUsername(e.target.value)}
                  placeholder="Username"
                  className="h-12 rounded-full bg-white/90 text-slate-900 placeholder:text-slate-400 border-0"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-slate-100">密码</Label>
                <Input
                  type="password"
                  value={loginPassword}
                  onChange={(e) => setLoginPassword(e.target.value)}
                  placeholder="Password"
                  className="h-12 rounded-full bg-white/90 text-slate-900 placeholder:text-slate-400 border-0"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void handleLogin();
                  }}
                />
              </div>

              <Button
                className="w-full h-12 rounded-full text-base font-semibold bg-pink-500 hover:bg-pink-600"
                onClick={handleLogin}
                disabled={loginLoading}
              >
                {loginLoading ? "登录中..." : "登录"}
              </Button>

              <div className="pt-2 border-t border-white/20">
                <div className="text-center text-sm text-slate-100 mb-3">Create An Account</div>
                <div className="space-y-2">
                  <Input
                    value={registerUsername}
                    onChange={(e) => setRegisterUsername(e.target.value)}
                    placeholder="注册账号"
                    className="h-10 rounded-full bg-white/90 text-slate-900 placeholder:text-slate-400 border-0"
                  />
                  <Input
                    type="password"
                    value={registerPassword}
                    onChange={(e) => setRegisterPassword(e.target.value)}
                    placeholder="注册密码"
                    className="h-10 rounded-full bg-white/90 text-slate-900 placeholder:text-slate-400 border-0"
                  />
                  <Input
                    value={registerInviteCode}
                    onChange={(e) => setRegisterInviteCode(e.target.value)}
                    placeholder="邀请码（可选）"
                    className="h-10 rounded-full bg-white/90 text-slate-900 placeholder:text-slate-400 border-0"
                  />
                  <Button className="w-full h-10 rounded-full bg-blue-600 hover:bg-blue-700" onClick={handleRegister}>
                    注册并登录
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  // 已登录：显示完整会员中心
  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
      <div>
        <h1 className="text-2xl font-bold">会员中心</h1>
          <p className="text-sm text-muted-foreground mt-1">已登录账号：{displayMe?.username || "-"} {showAdminTabs ? "（管理员）" : ""}</p>
          {showAdminTabs && Number(adminWithdraws?.filter((x: any) => String(x?.status || "pending") === "pending")?.length || 0) > 0 ? (
            <button
              className="mt-2 inline-flex items-center gap-2 rounded-full bg-amber-50 text-amber-700 border border-amber-200 px-3 py-1 text-sm hover:bg-amber-100"
              onClick={() => document.getElementById("withdraw-approval-card")?.scrollIntoView({ behavior: "smooth", block: "start" })}
            >
              <span className="inline-flex h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
              有 {adminWithdraws.filter((x: any) => String(x?.status || "pending") === "pending").length} 条提现申请待审批（点击查看）
            </button>
          ) : null}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => void enterSystem()} disabled={enteringApp}>
            {enteringApp ? "进入中…" : "进入系统"}
          </Button>
          <Button variant="destructive" onClick={handleLogout}>退出</Button>
        </div>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between gap-2">
            <CardTitle className="text-lg">我的状态</CardTitle>
            <Button size="sm" variant="outline" onClick={handleBindStore} disabled={bindingStore}>
              {bindingStore ? "绑定中..." : "绑定店铺"}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className={`grid gap-3 ${isAdminSession ? "grid-cols-2 md:grid-cols-4 lg:grid-cols-7" : "grid-cols-2 md:grid-cols-3 lg:grid-cols-5"}`}>
            <div className="rounded-lg border bg-slate-50 p-3">
              <div className="text-[11px] text-muted-foreground">账号</div>
              <div className="mt-1 text-sm font-medium truncate">{displayMe?.username || "-"}</div>
            </div>
            <div className="rounded-lg border bg-slate-50 p-3">
              <div className="text-[11px] text-muted-foreground">邀请码</div>
              <div className="mt-1 text-sm font-medium truncate">{displayMe?.invite_code || (isAdminSession ? "管理员" : "-")}</div>
            </div>
            <div className="rounded-lg border bg-slate-50 p-3">
              <div className="text-[11px] text-muted-foreground">积分余额</div>
              <div className="mt-1 text-sm font-semibold">
                {isAdminSession ? (
                  `¥${Number(adminDashboard?.summary?.total_recharge_amount ?? 0)}`
                ) : displayMe?.points_unavailable ? (
                  <span className="text-xs font-normal text-amber-700" title={displayMe?.points_error || ""}>
                    {displayMe?.points_error || "云端积分暂不可用"}
                  </span>
                ) : (
                  Number(displayMe?.points_balance ?? 0).toFixed(2).replace(/\.?0+$/, "")
                )}
              </div>
            </div>
            <div className="rounded-lg border bg-slate-50 p-3">
              <div className="text-[11px] text-muted-foreground">会员</div>
              <div className="mt-1">
                {isAdminSession ? (
                  <Badge>管理员</Badge>
                ) : (displayMe?.is_vip ? (
                  <Badge>会员</Badge>
                ) : (
                  <Badge variant="outline">试用会员</Badge>
                ))}
              </div>
            </div>
            <div className="rounded-lg border bg-slate-50 p-3">
              <div className="text-[11px] text-muted-foreground">会员到期</div>
              <div className="mt-1 text-sm font-medium truncate">
                {isAdminSession
                  ? "-"
                  : (displayMe?.is_vip ? (displayMe?.vip_expire_at || "-") : (displayMe?.trial_end_at || "-"))}
              </div>
            </div>

            {!isAdminSession ? (
              <>
                <div className={`rounded-lg border p-3 ${isCompanyVerifiedMember ? "bg-emerald-100 border-emerald-300" : "bg-slate-50"}`}>
                  <div className={`text-[11px] ${isCompanyVerifiedMember ? "text-emerald-800" : "text-muted-foreground"}`}>公司名称</div>
                  <div className={`mt-1 text-sm font-medium truncate ${isCompanyVerifiedMember ? "text-emerald-900" : ""}`}>{displayMe?.company_name || "-"}</div>
                </div>
                <div className="rounded-lg border bg-slate-50 p-3">
                  <div className="text-[11px] text-muted-foreground">主营类目</div>
                  <div className="mt-1 text-sm font-medium truncate">{displayMe?.main_category || "-"}</div>
                </div>
              </>
            ) : null}

            {isAdminSession ? (
              <>
                <div className="rounded-lg border bg-slate-50 p-3">
                  <div className="text-[11px] text-muted-foreground">会员总数</div>
                  <div className="mt-1 text-sm font-medium">{Number(adminDashboard?.summary?.total_users ?? adminUsers.length ?? 0)}</div>
                </div>
                <div className="rounded-lg border bg-slate-50 p-3">
                  <div className="text-[11px] text-muted-foreground">有效会员</div>
                  <div className="mt-1 text-sm font-medium">{`${Number(adminDashboard?.summary?.active_vip_users ?? 0)} 个`}</div>
                </div>
              </>
            ) : null}
          </div>

          <div className={`grid grid-cols-1 gap-3 ${isAdminSession ? "md:grid-cols-2" : ""}`}>
            <div className="rounded-xl border bg-gradient-to-r from-amber-50 to-orange-50 p-4 flex items-center justify-between">
              <div>
                <div className="text-xs text-amber-700">积分兑换会员</div>
                <div className="text-sm font-semibold mt-1">1500积分兑换1个月会员</div>
              </div>
              <Button size="sm" className="shrink-0" onClick={handleRedeem}>立即兑换</Button>
            </div>
            {isAdminSession ? (
              <div className="rounded-xl border bg-gradient-to-r from-emerald-50 to-cyan-50 p-4 flex items-center justify-between">
                <div>
                  <div className="text-xs text-emerald-700">提现申请</div>
                  <div className="text-sm font-semibold mt-1">提交积分提现到支付宝</div>
                </div>
                <Button size="sm" variant="outline" className="shrink-0" onClick={() => setWithdrawDialogOpen(true)}>
                  去申请
                </Button>
              </div>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <div className="space-y-4">




      <Card className="flex flex-col overflow-hidden">
          <CardHeader className="shrink-0 pb-3">
            <CardTitle>积分流水</CardTitle>
          </CardHeader>
          <CardContent className="shrink-0 pt-0 text-sm">
            <div
              className="h-[300px] max-h-[300px] overflow-y-auto overflow-x-hidden overscroll-contain rounded-lg border bg-slate-50/80 p-2 space-y-2 [scrollbar-gutter:stable]"
              role="region"
              aria-label="积分流水列表"
            >
              {ledger.length === 0 ? (
                <div className="h-full flex items-center justify-center text-muted-foreground">暂无流水</div>
              ) : (
                ledger.map((r) => (
                  <div key={r.id} className="border rounded bg-white p-2 flex items-center justify-between gap-2">
                    <div className="min-w-0 flex-1 break-words">{r.created_at} | {r.biz_type} | {r.remark || "-"}</div>
                    <div className={`shrink-0 whitespace-nowrap ${Number(r.change_amount) > 0 ? "text-emerald-600" : "text-red-600"}`}>
                      {Number(r.change_amount) > 0 ? "+" : ""}{r.change_amount}
                    </div>
                  </div>
                ))
              )}
            </div>
          </CardContent>
      </Card>

        {showAdminTabs ? (
          <Card id="withdraw-approval-card" className="border-slate-200 shadow-sm overflow-hidden">
            <CardHeader className="pb-3 bg-gradient-to-r from-slate-50 to-amber-50/40">
              <div className="flex items-center justify-between">
                <CardTitle className="text-lg">提现审批（管理员）</CardTitle>
                <button
                  className="rounded-full border border-amber-300 bg-amber-50 text-amber-700 text-xs px-3 py-1 hover:bg-amber-100"
                  onClick={() => {
                    const firstPending = adminWithdraws.find((x: any) => String(x?.status || "pending") === "pending");
                    if (firstPending) {
                      setSelectedWithdraw(firstPending);
                      setWithdrawDetailOpen(true);
                    }
                  }}
                  title="点击查看第一条待审批详情"
                >
                  待审批 {adminWithdraws.filter((x: any) => String(x?.status || "pending") === "pending").length}
                </button>
              </div>
            </CardHeader>
            <CardContent className="text-sm pt-4">
              {adminWithdraws.length === 0 ? <div className="text-muted-foreground">暂无待审批提现</div> : (
                <div className="overflow-auto border rounded-lg">
                  <table className="w-full min-w-[980px] text-xs">
                    <thead className="bg-slate-50">
                      <tr className="border-b">
                        <th className="text-left px-3 py-2">申请单号</th>
                        <th className="text-left px-3 py-2">用户ID</th>
                        <th className="text-left px-3 py-2">积分</th>
                        <th className="text-left px-3 py-2">到账金额</th>
                        <th className="text-left px-3 py-2">到账账号</th>
                        <th className="text-left px-3 py-2">申请时间</th>
                        <th className="text-left px-3 py-2">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {adminWithdraws.map((w) => (
                        <tr key={w.withdraw_no} className="border-b last:border-0 hover:bg-slate-50/70">
                          <td className="px-3 py-2 font-medium text-slate-900">{w.withdraw_no}</td>
                          <td className="px-3 py-2">{w.user_id}</td>
                          <td className="px-3 py-2">
                            <button className="text-blue-600 underline" onClick={() => { setSelectedWithdraw(w); setWithdrawDetailOpen(true); }}>
                              {w.points}
                            </button>
                          </td>
                          <td className="px-3 py-2">¥{w.amount_yuan}</td>
                          <td className="px-3 py-2 max-w-[220px] truncate" title={w.account}>{w.account}</td>
                          <td className="px-3 py-2">{w.created_at || "-"}</td>
                          <td className="px-3 py-2">
                            <div className="flex gap-2">
                              <Button size="sm" variant="outline" onClick={() => { setSelectedWithdraw(w); setWithdrawDetailOpen(true); }}>详情</Button>
                              {String(w?.status || "pending") === "pending" ? (
                                <>
                                  <Button size="sm" onClick={() => approveWithdraw(w.withdraw_no)}>通过</Button>
                                  <Button size="sm" variant="destructive" onClick={() => rejectWithdraw(w.withdraw_no)}>驳回</Button>
                                </>
                              ) : String(w?.status || "") === "rejected" ? (
                                <Badge variant="destructive">已驳回</Badge>
                              ) : (
                                <Badge className="bg-emerald-600">已审批</Badge>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        ) : null}

        {showAdminTabs ? (
          <Card>
            <CardHeader><CardTitle>会员管理（管理员）</CardTitle></CardHeader>
            <CardContent className="text-sm h-[360px] overflow-hidden">
              {adminCompanyGroups.boundGroups.length === 0 && adminCompanyGroups.unboundUsers.length === 0 ? (
                <div className="text-muted-foreground">暂无用户</div>
              ) : (
                <div className="h-full overflow-auto space-y-3">
                  {adminCompanyGroups.boundGroups.map((g) => {
                    const companyOnline = g.users.some((x: any) => Number(x?.online || 0) === 1);
                    const first = g.users[0] || {};
                    return (
                      <div key={g.company} className={`border rounded p-2 ${companyOnline ? "bg-emerald-50 border-emerald-300" : ""}`}>
                        <button
                          className="w-full text-left"
                          onClick={() => openMemberDetail(first)}
                        >
                          <div className={`font-medium ${companyOnline ? "text-emerald-700" : ""}`}>
                            公司：{g.company}（账号数：{g.users.length}）
                          </div>
                          <div className="text-xs text-muted-foreground mt-1">
                            试用到期：{first?.trial_end_at || "-"} ｜ 在线账号：{g.users.filter((x: any) => Number(x?.online || 0) === 1).length}
                          </div>
                        </button>
                      </div>
                    );
                  })}

                  {adminCompanyGroups.unboundUsers.length > 0 ? (
                    <div className="pt-1">
                      <div className="text-xs text-muted-foreground mb-1">未绑定公司账号</div>
                      <div className="space-y-2">
                        {adminCompanyGroups.unboundUsers.map((u: any) => {
                          const online = Number(u?.online || 0) === 1;
                          return (
                            <button
                              key={`unbound-${u.id}`}
                              className={`w-full text-left border rounded p-2 hover:bg-slate-50 ${online ? "bg-emerald-50 border-emerald-300" : ""}`}
                              onClick={() => openMemberDetail(u)}
                            >
                              <span className={online ? "text-emerald-700 font-medium" : ""}>
                                #{u.id} | {u.username} | 余额: {u.points_balance ?? 0} | 试用到期: {u.trial_end_at || "-"} | 在线: {online ? "在线" : "离线"} | 最后活跃: {u.online_last_seen_at || "-"}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ) : null}
                </div>
              )}
            </CardContent>
          </Card>
        ) : null}

        {showAdminTabs ? (
          <Card>
            <CardHeader><CardTitle>客户节点（管理员）</CardTitle></CardHeader>
            <CardContent className="text-sm h-[360px] overflow-hidden">
              {adminAgents.length === 0 ? <div className="text-muted-foreground">暂无节点</div> : (
                <div className="h-full overflow-auto border rounded">
                  <table className="w-full min-w-[860px] text-xs">
                    <thead className="bg-slate-50">
                      <tr className="border-b">
                        <th className="text-left px-2 py-2">节点ID</th>
                        <th className="text-left px-2 py-2">客户名</th>
                        <th className="text-left px-2 py-2">版本</th>
                        <th className="text-left px-2 py-2">唯一ID</th>
                        <th className="text-left px-2 py-2">状态</th>
                        <th className="text-left px-2 py-2">最后心跳</th>
                      </tr>
                    </thead>
                    <tbody>
                      {adminAgents.map((a, idx) => {
                        const lastSeen = String(a?.last_seen_at || "").trim();
                        const clientDisplayName =
                          String(a?.company_name || "").trim() ||
                          String(a?.username || "").trim() ||
                          String(a?.display_client_name || "").trim() ||
                          String(a?.client_name || "").trim() ||
                          "-";
                        let online = false;
                        if (lastSeen) {
                          const ts = new Date(lastSeen.replace(" ", "T")).getTime();
                          if (!Number.isNaN(ts)) {
                            online = Date.now() - ts <= 5 * 60 * 1000;
                          }
                        }
                        const stateText = online ? "在线" : "离线";
                        return (
                          <tr key={`${a.agent_id}-${idx}`} className="border-b last:border-0">
                            <td className="px-2 py-2 font-mono">{a.agent_id || "-"}</td>
                            <td className="px-2 py-2">{clientDisplayName}</td>
                            <td className="px-2 py-2">{a.app_version || "-"}</td>
                            <td className="px-2 py-2 font-mono">{a.machine_id || a.agent_id || "-"}</td>
                            <td className="px-2 py-2">
                              <span className={online ? "text-emerald-600" : "text-rose-600"}>{stateText}</span>
                              <span className="text-muted-foreground ml-1">({a.status || "-"})</span>
                            </td>
                            <td className="px-2 py-2">{lastSeen || "-"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        ) : null}

        {showAdminTabs ? (
          <Card>
            <CardHeader><CardTitle>关键词回传（管理员）</CardTitle></CardHeader>
            <CardContent className="text-sm h-[360px] overflow-hidden">
              <div className="mb-2 flex items-center justify-between gap-2">
                <label className="text-xs text-muted-foreground inline-flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={adminKeywordReports.length > 0 && selectedKeywordReportIds.length === adminKeywordReports.length}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedKeywordReportIds(adminKeywordReports.map((x) => Number(x?.id || 0)).filter((x) => x > 0));
                      } else {
                        setSelectedKeywordReportIds([]);
                      }
                    }}
                  />
                  全选（已选 {selectedKeywordReportIds.length}）
                </label>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={deleteSelectedKeywordReports}
                  disabled={selectedKeywordReportIds.length <= 0}
                >
                  批量删除
                </Button>
              </div>
              {adminKeywordReports.length === 0 ? <div className="text-muted-foreground">暂无回传</div> : (
                <div className="h-full overflow-y-auto pr-1 space-y-2">
                  {adminKeywordReports.map((r) => (
                    <div key={r.id} className="w-full border rounded p-2 hover:bg-slate-50">
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          checked={selectedKeywordReportIds.includes(Number(r.id))}
                          onChange={(e) => toggleKeywordReport(Number(r.id), e.target.checked)}
                          onClick={(e) => e.stopPropagation()}
                        />
                        <button
                          className="flex-1 text-left"
                          onClick={() => openKeywordDetail(Number(r.id))}
                        >
                          {r.created_at} | 节点: {r.agent_id} | 日期: {r.report_date} | 条数: {r.item_count || 0}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        ) : null}
      </div>

      {showAdminTabs ? (
        showFloatRecharge ? (
          <div className="fixed right-4 top-1/2 -translate-y-1/2 z-[60]">
            <button
              className="relative h-16 w-16 rounded-full bg-gradient-to-br from-amber-400 to-orange-500 text-white shadow-xl border-2 border-amber-200 flex items-center justify-center hover:scale-105 transition"
              onClick={openRechargeByFloat}
              title="充值"
            >
              <span className="text-sm font-extrabold tracking-wide">充值</span>
            </button>
            <button
              className="absolute -top-2 -right-2 h-6 w-6 rounded-full bg-black/70 text-white text-sm leading-6 text-center hover:bg-black"
              onClick={() => setShowFloatRecharge(false)}
              title="关闭"
            >
              ×
            </button>
          </div>
        ) : (
          <button
            className="fixed right-4 top-1/2 -translate-y-1/2 z-[60] h-12 w-12 rounded-full bg-gradient-to-br from-amber-400 to-orange-500 text-white text-xs font-bold shadow-lg"
            onClick={() => setShowFloatRecharge(true)}
            title="打开充值"
          >
            充
          </button>
        )
      ) : null}

      <Dialog open={withdrawDialogOpen} onOpenChange={setWithdrawDialogOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>提现申请</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <Label>提现积分</Label>
                <Input
                  type="number"
                  value={withdrawPoints}
                  onChange={(e) => {
                    setWithdrawPoints(e.target.value === "" ? "" : Number(e.target.value));
                    if (withdrawErrors.points) {
                      setWithdrawErrors((p) => ({ ...p, points: undefined }));
                    }
                  }}
                  className={withdrawErrors.points ? "border-red-500 focus-visible:ring-red-500" : ""}
                />
                {withdrawErrors.points ? <p className="mt-1 text-xs text-red-600">此为必填项</p> : null}
              </div>
              <div>
                <Label>到账账号（支付宝）</Label>
                <Input
                  value={withdrawAccount}
                  onChange={(e) => {
                    setWithdrawAccount(e.target.value);
                    if (withdrawErrors.account) {
                      setWithdrawErrors((p) => ({ ...p, account: undefined }));
                    }
                  }}
                  placeholder="请输入支付宝账号"
                  className={withdrawErrors.account ? "border-red-500 focus-visible:ring-red-500" : ""}
                />
                {withdrawErrors.account ? <p className="mt-1 text-xs text-red-600">此为必填项</p> : null}
              </div>
            </div>
            <div className="text-xs text-muted-foreground">到账金额按 1:1 积分折算，仅支持支付宝渠道。</div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setWithdrawDialogOpen(false)}>取消</Button>
              <Button onClick={async () => {
                const ok = await handleWithdraw();
                if (ok) {
                  setWithdrawDialogOpen(false);
                }
              }}>提交提现</Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={rechargeCenterOpen && showAdminTabs} onOpenChange={setRechargeCenterOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>充值中心</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>充值（V1）</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
                <div><Label>金额（元）</Label><Input type="number" value={amount} onChange={(e) => setAmount(Number(e.target.value || 0))} /></div>
                  <Button onClick={() => handleRecharge("wechat")} disabled={adminConsoleLoggedIn}>微信下单</Button>
                  <Button onClick={() => handleRecharge("alipay")} disabled={adminConsoleLoggedIn}>支付宝下单</Button>
              </div>
              <div className="text-xs text-muted-foreground">正式环境请在“配置管理”中启用支付并配置签名密钥；支付平台回调将自动入账。</div>
              <div className="flex gap-2 items-center">
                <Input value={lastOrderNo} onChange={(e) => setLastOrderNo(e.target.value)} placeholder="订单号" className="max-w-sm" />
                  <Button variant="outline" onClick={() => handleCheckOrder()}>查询订单</Button>
                <Button variant="outline" onClick={handleMockPaid}>模拟支付成功</Button>
              </div>
              {paymentInfo ? <div className="text-xs text-muted-foreground">支付信息已生成，请在弹窗中完成支付。</div> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>充值订单</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-sm max-h-[260px] overflow-auto">
                {orders.length === 0 ? <div className="text-muted-foreground">暂无订单</div> : orders.map((o) => (
                  <div key={o.id || o.order_no} className="border rounded p-2 flex items-center justify-between">
                  <div>{o.created_at} | {o.order_no} | {o.channel} | ¥{o.amount_yuan}</div>
                  <Badge variant={o.status === "paid" ? "default" : "outline"}>{o.status}</Badge>
                </div>
              ))}
            </CardContent>
          </Card>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={withdrawDetailOpen} onOpenChange={setWithdrawDetailOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>提现申请详情</DialogTitle>
          </DialogHeader>
          {selectedWithdraw ? (
            <div className="space-y-3 text-sm">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div><Label>申请单号</Label><Input value={selectedWithdraw.withdraw_no || "-"} disabled /></div>
                <div><Label>用户ID</Label><Input value={String(selectedWithdraw.user_id ?? "-")} disabled /></div>
                <div><Label>提现积分</Label><Input value={String(selectedWithdraw.points ?? 0)} disabled /></div>
                <div><Label>到账金额</Label><Input value={`¥${selectedWithdraw.amount_yuan ?? 0}`} disabled /></div>
                <div className="md:col-span-2"><Label>到账账号</Label><Input value={selectedWithdraw.account || "-"} disabled /></div>
                <div><Label>状态</Label><Input value={selectedWithdraw.status || "pending"} disabled /></div>
                <div><Label>申请时间</Label><Input value={selectedWithdraw.created_at || "-"} disabled /></div>
                <div><Label>更新时间</Label><Input value={selectedWithdraw.updated_at || "-"} disabled /></div>
                <div><Label>拒绝原因</Label><Input value={selectedWithdraw.reject_reason || "-"} disabled /></div>
              </div>

              <div className="flex justify-end gap-2 pt-1">
                <Button variant="outline" onClick={() => setWithdrawDetailOpen(false)}>关闭</Button>
                {String(selectedWithdraw?.status || "pending") === "pending" ? (
                  <>
                    <Button onClick={async () => {
                      await approveWithdraw(String(selectedWithdraw.withdraw_no || ""));
                      setWithdrawDetailOpen(false);
                    }}>通过</Button>
                    <Button variant="destructive" onClick={async () => {
                      await rejectWithdraw(String(selectedWithdraw.withdraw_no || ""));
                      setWithdrawDetailOpen(false);
                    }}>驳回</Button>
                  </>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">暂无详情数据</div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={keywordDetailOpen} onOpenChange={setKeywordDetailOpen}>
        <DialogContent className="sm:max-w-5xl">
          <DialogHeader>
            <DialogTitle>关键词回传明细</DialogTitle>
          </DialogHeader>
          {keywordDetailLoading ? (
            <div className="text-sm text-muted-foreground">正在加载明细...</div>
          ) : keywordDetail?.report ? (
            <div className="space-y-3 text-sm">
              <div className="text-xs text-muted-foreground">
                批次：{keywordDetail?.report?.batch_no || "-"} ｜ 节点：{keywordDetail?.report?.agent_id || "-"} ｜ 日期：{keywordDetail?.report?.report_date || "-"} ｜ 条数：{keywordDetail?.report?.item_count || 0}
                  </div>
              <div className="max-h-[420px] overflow-auto border rounded">
                <table className="w-full min-w-[980px] text-xs">
                  <thead className="bg-slate-50 sticky top-0">
                    <tr className="border-b">
                      <th className="text-left px-2 py-2">关键词</th>
                      <th className="text-left px-2 py-2">曝光</th>
                      <th className="text-left px-2 py-2">点击</th>
                      <th className="text-left px-2 py-2">点击率</th>
                      <th className="text-left px-2 py-2">关键词指数</th>
                      <th className="text-left px-2 py-2">产品ID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(Array.isArray(keywordDetail?.items) ? keywordDetail.items : []).map((it: any, idx: number) => (
                      <tr key={`${it?.keyword || "kw"}-${idx}`} className="border-b last:border-0">
                        <td className="px-2 py-2">{it?.keyword || "-"}</td>
                        <td className="px-2 py-2">{it?.exposure ?? 0}</td>
                        <td className="px-2 py-2">{it?.click ?? 0}</td>
                        <td className="px-2 py-2">{`${(Number(it?.ctr ?? 0) * 100).toFixed(2)}%`}</td>
                        <td className="px-2 py-2">{it?.keyword_index ?? 0}</td>
                        <td className="px-2 py-2">{it?.product_id || "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <div className="text-sm text-muted-foreground">暂无明细数据</div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={memberDetailOpen} onOpenChange={setMemberDetailOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>会员详情编辑</DialogTitle>
          </DialogHeader>
          {selectedMember ? (
            <div className="space-y-3 text-sm">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                <div><Label>会员ID</Label><Input value={String(selectedMember.id)} disabled /></div>
                <div><Label>账号</Label><Input value={String(selectedMember.username || "")} disabled /></div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                <div><Label>公司名称</Label><Input value={String(selectedMember.company_name || "-")} disabled /></div>
                <div><Label>主营类目</Label><Input value={String(selectedMember.main_category || "-")} disabled /></div>
                <div><Label>会员类型</Label><Input value={String(selectedMember.is_verified || "-")} disabled /></div>
                <div><Label>开通年限</Label><Input value={String(selectedMember.service_years || "-")} disabled /></div>
                <div><Label>店铺星级</Label><Input value={String(selectedMember.page_level_star || "-")} disabled /></div>
              </div>

              <div className="rounded border bg-slate-50 p-2">
                <div className="text-xs text-muted-foreground mb-1">
                  同公司账号列表（{selectedCompanyUsers.length}）
                </div>
                {selectedCompanyUsers.length <= 0 ? (
                  <div className="text-xs text-muted-foreground">暂无同公司账号</div>
                ) : (
                  <div className="space-y-1 max-h-36 overflow-auto">
                    {selectedCompanyUsers.map((x: any) => {
                      const online = Number(x?.online || 0) === 1;
                      const active = Number(selectedMember?.id || 0) === Number(x?.id || 0);
                      return (
                        <button
                          key={`same-company-${x.id}`}
                          type="button"
                          onClick={() => openMemberDetail(x)}
                          className={`w-full text-xs border rounded px-2 py-1 flex items-center justify-between gap-2 ${active ? "bg-emerald-50 border-emerald-300" : "bg-white hover:bg-slate-50"}`}
                        >
                          <span className="truncate">#{x.id} | {x.username || "-"}</span>
                          <span className={online ? "text-emerald-600" : "text-slate-500"}>{online ? "在线" : "离线"}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  <div>
                  <Label>控制策略</Label>
                  <select className="w-full border rounded px-2 py-2" value={memberForm.mode} onChange={(e) => setMemberForm((p: any) => ({ ...p, mode: e.target.value }))}>
                    <option value="normal">默认规则</option>
                    <option value="force_allow">强制允许</option>
                    <option value="force_block">强制禁用</option>
                  </select>
                  </div>
                <div><Label>备注</Label><Input value={memberForm.note} onChange={(e) => setMemberForm((p: any) => ({ ...p, note: e.target.value }))} /></div>
                </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                <div><Label>积分余额</Label><Input type="number" inputMode="numeric" value={memberForm.points_balance} onChange={(e) => setMemberForm((p: any) => ({ ...p, points_balance: e.target.value }))} /></div>
                <div><Label>重置密码（留空不改）</Label><Input type="password" value={memberForm.password} onChange={(e) => setMemberForm((p: any) => ({ ...p, password: e.target.value }))} /></div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                <div><Label>试用开始</Label><Input value={memberForm.trial_start_at} onChange={(e) => setMemberForm((p: any) => ({ ...p, trial_start_at: e.target.value }))} placeholder="YYYY-MM-DD HH:mm:ss" /></div>
                <div><Label>试用结束</Label><Input value={memberForm.trial_end_at} onChange={(e) => setMemberForm((p: any) => ({ ...p, trial_end_at: e.target.value }))} placeholder="YYYY-MM-DD HH:mm:ss" /></div>
                <div><Label>会员到期</Label><Input value={memberForm.vip_expire_at} onChange={(e) => setMemberForm((p: any) => ({ ...p, vip_expire_at: e.target.value }))} placeholder="YYYY-MM-DD HH:mm:ss / 留空" /></div>
                      </div>

              <div className="flex justify-between gap-2 pt-2">
                <Button variant="destructive" onClick={deleteMemberInDetail}>删除会员</Button>
                    <div className="flex gap-2">
                  <Button variant="outline" onClick={() => setMemberDetailOpen(false)}>取消</Button>
                  <Button onClick={saveMemberDetail}>保存更改</Button>
                    </div>
                  </div>
              </div>
          ) : null}
        </DialogContent>
      </Dialog>

      <Dialog open={paymentDialogOpen} onOpenChange={setPaymentDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{paymentInfo?.provider === "wechat" ? "微信支付" : "支付宝支付"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <div className="flex items-center justify-between">
              <div>订单号：{paymentInfo?.out_trade_no || lastOrderNo || "-"}</div>
              <Badge variant={paymentStatus === "paid" ? "default" : "outline"}>{paymentStatus}</Badge>
            </div>
            {!!paymentInfo?.gateway_notice ? (
              <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">{paymentInfo.gateway_notice}</div>
            ) : null}
            {paymentInfo?.provider === "wechat" ? (
              <div className="space-y-2">
                <div className="text-muted-foreground">请使用微信扫码支付</div>
                {wechatQrDataUrl ? <img src={wechatQrDataUrl} alt="微信支付二维码" className="w-[240px] h-[240px] rounded border mx-auto" /> : null}
                <div className="font-mono text-[11px] break-all bg-muted/50 rounded p-2">{paymentInfo?.qr_content || "-"}</div>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="text-muted-foreground">请使用支付宝扫码支付</div>
                {alipayQrDataUrl ? <img src={alipayQrDataUrl} alt="支付宝支付二维码" className="w-[240px] h-[240px] rounded border mx-auto" /> : null}
                <a href={paymentInfo?.pay_url || "#"} target="_blank" rel="noreferrer" className="text-blue-600 underline break-all text-xs">{paymentInfo?.pay_url || "-"}</a>
              </div>
            )}
            <div className="flex gap-2 justify-end flex-wrap">
              <Button variant="outline" onClick={() => handleCheckOrder()}>查询状态</Button>
              <Button variant="outline" onClick={pollOrderStatus} disabled={polling}>{polling ? "轮询中..." : "自动轮询"}</Button>
              <Button variant="outline" onClick={handleMockPaid}>模拟成功</Button>
              {paymentInfo?.provider === "alipay" && paymentInfo?.pay_url ? (
                <Button variant="outline" onClick={() => window.open(paymentInfo.pay_url, "_blank", "noopener,noreferrer")}>打开支付宝</Button>
              ) : null}
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}