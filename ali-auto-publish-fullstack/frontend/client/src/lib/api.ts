/**
 * 前端 API 调用层
 * 所有与后端 FastAPI 的通信都通过此模块
 *
 * 【如何修改】
 * - 添加新接口 → 在对应的 section 中添加新函数
 * - 修改请求参数 → 修改对应函数的参数和 payload
 * - 修改基础 URL → 修改 API_BASE 常量（开发环境通过 Vite proxy 代理）
 */
import axios from "axios";

// 浏览器开发态走 /api（由 Vite 代理），Electron/本地 file 协议直连本地后端
const isElectron = typeof window !== "undefined" && !!(window as any)?.desktopEnv?.isElectron;
const isFileProtocol = typeof window !== "undefined" && window.location.protocol === "file:";
const isElectronUA = typeof navigator !== "undefined" && /Electron/i.test(navigator.userAgent || "");
const isDesktopRuntime = !!(isElectron || isFileProtocol || isElectronUA);

/** 桌面端本机 backend 根地址（可由 Electron getRuntimeInfo 解析端口） */
let backendHttpBase = isDesktopRuntime ? "http://127.0.0.1:8000" : "";

export function getBackendHttpBase(): string {
  return backendHttpBase;
}

function setBackendHttpBase(base: string) {
  backendHttpBase = (base || "").replace(/\/+$/, "");
  api.defaults.baseURL = backendHttpBase ? `${backendHttpBase}/api` : "/api";
}

/** 与 Electron main.cjs 的 BACKEND_PORT 对齐 */
export async function initDesktopBackendConnection(): Promise<string> {
  if (!isDesktopRuntime) {
    setBackendHttpBase("");
    return "";
  }
  let port = "8000";
  try {
    const info = await (window as any)?.desktopEnv?.getRuntimeInfo?.();
    const p = String(info?.backendPort || "").trim();
    if (p) port = p;
  } catch {
    // 使用默认 8000
  }
  const base = `http://127.0.0.1:${port}`;
  setBackendHttpBase(base);
  return base;
}

const API_BASE = backendHttpBase ? `${backendHttpBase}/api` : "/api";

/** 云端会员权威 API 域名（桌面端备用直连线路） */
export const DEFAULT_CLOUD_MEMBERSHIP_BASE = "https://echo-yiwu.cloud/api/membership";

function resolveCloudMembershipBase(): string {
  const fromEnv = String(import.meta.env.VITE_CLOUD_MEMBERSHIP_API_BASE || "").trim();
  if (fromEnv) return fromEnv.replace(/\/+$/, "");
  // 桌面端直连云端域名（与第 1/3 次可登录的安装包一致）；网络异常时由拦截器回退本机 backend 代理
  if (isElectron || isFileProtocol || isElectronUA) {
    return DEFAULT_CLOUD_MEMBERSHIP_BASE;
  }
  // 浏览器开发：走 Vite /cloud-api 代理到云端，避免 CORS
  return "/cloud-api/membership";
}

/** 运行时解析（避免模块加载早于 preload 时误判为 /cloud-api） */
function getCloudMembershipBase(): string {
  return resolveCloudMembershipBase();
}

export function isDesktopClient(): boolean {
  return !!(isElectron || isFileProtocol || isElectronUA);
}

/** 浏览器 dev（pnpm run dev）走 Vite /api → 本机 backend，避免 /cloud-api 直连云端失败 */
function useLocalMembershipProxy(): boolean {
  if (getBackendHttpBase()) return true;
  return import.meta.env.DEV && !isDesktopClient();
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** 桌面端：等待本机 backend 就绪（安装包自动拉起 ali-backend.exe） */
export async function waitLocalBackendReady(timeoutMs: number = 45000): Promise<boolean> {
  if (isDesktopRuntime) {
    await initDesktopBackendConnection();
  }
  if (!getBackendHttpBase()) return true;
  if (typeof window !== "undefined" && (window as any)?.desktopEnv?.waitBackendReady) {
    try {
      return !!(await (window as any).desktopEnv.waitBackendReady(timeoutMs));
    } catch {
      // fallback to fetch poll
    }
  }
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`${getBackendHttpBase()}/api/health`, { cache: "no-store" });
      if (res.ok) return true;
    } catch {
      // retry
    }
    await sleep(500);
  }
  return false;
}

const api = axios.create({
  baseURL: API_BASE,
  timeout: isDesktopClient() ? 90000 : 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

/** 会员/积分 API（桌面端默认直连云端；非登录接口网络失败时可回退本机代理） */
const cloudMembershipApi = axios.create({
  baseURL: DEFAULT_CLOUD_MEMBERSHIP_BASE,
  timeout: isDesktopClient() ? 15000 : 15000,
  headers: {
    "Content-Type": "application/json",
  },
});

cloudMembershipApi.interceptors.request.use((config) => {
  config.baseURL = getCloudMembershipBase();
  return attachMembershipRequestHeaders(config);
});

function isMembershipNetworkFailure(error: any): boolean {
  if (error?.response) return false;
  const code = String(error?.code || "");
  const msg = String(error?.message || "");
  return (
    code === "ECONNABORTED" ||
    code === "ECONNREFUSED" ||
    /Network Error|ERR_CONNECTION|timeout of \d+ms exceeded|无法连接|refused/i.test(msg)
  );
}

async function restartDesktopBackendIfNeeded(): Promise<boolean> {
  if (!isDesktopClient()) return false;
  try {
    const fn = (window as any)?.desktopEnv?.restartBackend;
    if (typeof fn !== "function") return false;
    return !!(await fn());
  } catch {
    return false;
  }
}

const MEMBER_TOKEN_KEY = "membership_token";
const ADMIN_KEY_STORE = "membership_admin_key";
const CONTROL_ADMIN_KEY_STORE = "control_admin_key";

function getDeviceId(): string {
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
}

function getAdminHeaders(): Record<string, string> {
  try {
    const adminKey =
      localStorage.getItem(ADMIN_KEY_STORE) ||
      localStorage.getItem(CONTROL_ADMIN_KEY_STORE) ||
      "";
    if (adminKey) return { "X-Admin-Key": adminKey };
  } catch {
    // ignore
  }
  return {};
}

function withAdminConfig(config?: Record<string, any>) {
  const headers = { ...(config?.headers || {}), ...getAdminHeaders() };
  return { ...(config || {}), headers };
}

export function getMembershipToken(): string {
  try {
    return localStorage.getItem(MEMBER_TOKEN_KEY) || "";
  } catch {
    return "";
  }
}

/** 当前请求是否具备会员 token 或管理员钥匙（用于轮询前判断） */
export function hasApiCredentials(): boolean {
  const token = getMembershipToken();
  if (token) return true;
  try {
    const adminKey =
      localStorage.getItem(ADMIN_KEY_STORE) ||
      localStorage.getItem(CONTROL_ADMIN_KEY_STORE) ||
      "";
    return !!adminKey;
  } catch {
    return false;
  }
}

/** 当前是否为管理员控制台会话（已登录且持有 admin_key） */
export function isAdminConsoleSession(): boolean {
  try {
    const loggedIn = localStorage.getItem("admin_console_logged_in") === "1";
    const adminKey =
      localStorage.getItem(ADMIN_KEY_STORE) ||
      localStorage.getItem(CONTROL_ADMIN_KEY_STORE) ||
      "";
    return loggedIn && !!adminKey;
  } catch {
    return false;
  }
}

export function setMembershipToken(token: string) {
  try {
    if (token) localStorage.setItem(MEMBER_TOKEN_KEY, token);
    else localStorage.removeItem(MEMBER_TOKEN_KEY);
  } catch {
    // ignore
  }
  notifyAuthChanged();
}

/** 无 token 时清理残留管理员标记，避免「显示已登录管理员但弹登录框」 */
export function clearStaleAuthSession() {
  if (getMembershipToken()) return;
  try {
    localStorage.removeItem("admin_console_logged_in");
    localStorage.removeItem("admin_console_user");
    localStorage.removeItem(ADMIN_KEY_STORE);
    localStorage.removeItem(CONTROL_ADMIN_KEY_STORE);
  } catch {
    // ignore
  }
}

export function notifyAuthChanged() {
  try {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("membership:auth-changed"));
    }
  } catch {
    // ignore
  }
}

/** 桌面端登录前等待本机 backend（会员/管理员登录均依赖） */
export async function ensureDesktopBackendForLogin(timeoutMs: number = 45000): Promise<void> {
  if (!isDesktopClient()) return;
  if (typeof window !== "undefined" && (window as any)?.desktopEnv?.waitBackendReady) {
    const ok = !!(await (window as any).desktopEnv.waitBackendReady(timeoutMs));
    if (!ok) {
      throw new Error(
        "本地服务尚未就绪，请关闭软件后重新打开；若仍失败请联系技术支持并提供 runtime.log"
      );
    }
    return;
  }
  const ok = await waitLocalBackendReady(timeoutMs);
  if (!ok) {
    throw new Error(
      "本地服务尚未就绪，请关闭软件后重新打开；若仍失败请联系技术支持并提供 runtime.log"
    );
  }
}

function attachMembershipRequestHeaders(config: import("axios").InternalAxiosRequestConfig) {
  const token = getMembershipToken();
  config.headers = config.headers || {};
  if (token) {
    (config.headers as any).Authorization = `Bearer ${token}`;
  }
  (config.headers as any)["X-Client-Device-Id"] = getDeviceId();
  // 仅管理员控制台会话附带 X-Admin-Key，避免会员请求误带残留密钥导致读到完整 config
  if (isAdminConsoleSession()) {
    const adminHeaders = getAdminHeaders();
    if (adminHeaders["X-Admin-Key"]) {
      (config.headers as any)["X-Admin-Key"] = adminHeaders["X-Admin-Key"];
    }
  }
  return config;
}

async function handleApiResponseError(error: any) {
  const req = error?.config as any;
  const method = String(req?.method || "").toLowerCase();
  const shouldRetryNetworkGet = !!getBackendHttpBase() && method === "get" && !error?.response;
  const retryCount = Number(req?.__retryCount || 0);

  if (shouldRetryNetworkGet && retryCount < 6) {
    req.__retryCount = retryCount + 1;
    const waitMs = Math.min(250 * Math.pow(2, retryCount), 2000);
    await new Promise((r) => setTimeout(r, waitMs));
    return api.request(req);
  }

  const detail = error.response?.data?.detail;
  const status = error.response?.status;
  const detailObj = detail && typeof detail === "object" ? detail : null;
  const detailReason = String((detailObj as any)?.reason || "").trim();
  const detailMessage = String((detailObj as any)?.message || "").trim();
  const detailText = detailMessage || String(detail || "");

  if (status === 401 || status === 403) {
    const path =
      typeof window !== "undefined"
        ? String(window.location.hash || "").replace(/^#/, "") || window.location.pathname || ""
        : "";
    if (path && path !== "/membership" && !path.startsWith("/membership?")) {
      if (typeof window !== "undefined") {
        const reason = (() => {
          const headerReason = String(error.response?.headers?.["x-auth-reason"] || "").trim();
          if (headerReason) return headerReason;
          if (detailReason) return detailReason;
          if (detailText.includes("未绑定店铺")) return "store_not_bound";
          if (
            detailText.includes("登录") &&
            (detailText.includes("失效") || detailText.includes("过期") || detailText.includes("重新登录"))
          ) {
            return "auth_expired";
          }
          if (detailText.includes("设备校验失败") || detailText.includes("会话校验失败")) {
            return "session_invalid";
          }
          if (detailText.includes("非会员") || detailText.includes("试用期已过")) {
            return "not_member";
          }
          return "forbidden";
        })();

        // 管理员无需绑定店铺；后端已放行时此处避免误弹提示
        if (reason === "store_not_bound" && isAdminConsoleSession()) {
          return Promise.reject(error);
        }

        window.dispatchEvent(
          new CustomEvent("membership:required", {
            detail: {
              reason,
              path,
              status,
              message: detailText || "请先登录会员中心",
            },
          })
        );
      }
    }
  }

  const isConnRefused =
    !error?.response &&
    (String(error?.code || "") === "ECONNREFUSED" ||
      /Network Error|ERR_CONNECTION|无法连接|refused/i.test(String(error?.message || "")));
  const reqUrl = String(req?.baseURL || "") + String(req?.url || "");
  const isDirectCloudReq =
    reqUrl.includes("/cloud-api/") ||
    reqUrl.includes("echo-yiwu.cloud") ||
    reqUrl.includes(DEFAULT_CLOUD_MEMBERSHIP_BASE);
  const isMembershipProxyReq =
    !!getBackendHttpBase() && (reqUrl.includes("/api/membership") || reqUrl.includes("/membership/"));
  const isLocalApiReq = !!getBackendHttpBase() && !isDirectCloudReq;
  const isTimeout =
    String(error?.code || "") === "ECONNABORTED" ||
    /timeout of \d+ms exceeded/i.test(String(error?.message || ""));
  const isTlsOrProxyDns =
    !error?.response &&
    (isDirectCloudReq || isMembershipProxyReq) &&
    /SSL|TLS|schannel|ERR_SSL|certificate|handshake|ECONNRESET|198\.18\./i.test(
      String(error?.message || "") + String(error?.code || "")
    );

  let raw: string;
  if (isTlsOrProxyDns && (isDirectCloudReq || isMembershipProxyReq)) {
    raw =
      "无法连接云端会员服务：请关闭 Clash/代理，或将 echo-yiwu.cloud 设为直连；也可在 hosts 添加：43.164.196.172 echo-yiwu.cloud";
  } else if (isTimeout && (isMembershipProxyReq || isDirectCloudReq)) {
    raw = "无法连接会员云服务，请确认本机可正常上网后重启软件；若仍失败请联系技术支持";
  } else if (isTimeout && isLocalApiReq) {
    raw = isDesktopClient()
      ? "本地服务响应超时，请关闭软件后重新打开"
      : "本地后端响应超时，请确认 backend 已启动";
  } else if (isConnRefused && isMembershipProxyReq) {
    raw = isDesktopClient()
      ? "本地服务尚未就绪，请关闭软件后重新打开；若仍失败请联系技术支持"
      : "本地后端未启动或无法连接，请在 backend 目录运行：python run.py";
  } else if (isConnRefused && isLocalApiReq) {
    raw = isDesktopClient()
      ? "本地服务尚未就绪，请关闭软件后重新打开；若仍失败请联系技术支持"
      : "本地后端未启动或无法连接，请在 backend 目录运行：python run.py";
  } else if (isConnRefused && isDirectCloudReq) {
    raw = "无法连接云端会员服务，请检查网络连接，或暂时关闭 Clash/代理软件后重试";
  } else {
    raw = detailMessage || detail || error.message || "请求失败";
  }
  if (
    status === 400 &&
    (isDirectCloudReq || isMembershipProxyReq) &&
    /云端会员服务暂不可用|不可达/i.test(String(raw))
  ) {
    raw = `${raw}（本机 VPN/Clash 可能劫持了 DNS；系统已尝试 DoH+直连 IP，请重启后端或设置 CLOUD_MEMBERSHIP_API_IP）`;
  }
  if (status === 500 && (isDirectCloudReq || isMembershipProxyReq)) {
    raw = detailText
      ? `云端会员服务异常(500)：${detailText}`
      : "云端会员服务异常(500)，请确认云端已启动且本机可访问 echo-yiwu.cloud；开发环境请重启 pnpm run dev";
  }
  const message =
    typeof raw === "string"
      ? raw
      : (() => {
          try {
            const maybeMsg = (raw as any)?.message;
            return typeof maybeMsg === "string" && maybeMsg ? maybeMsg : JSON.stringify(raw);
          } catch {
            return String(raw);
          }
        })();
  console.error("[API Error]", message, { detail, status });
  return Promise.reject(new Error(message));
}

api.interceptors.request.use((config) => attachMembershipRequestHeaders(config));

/** 桌面端：直连云端失败时，回退本机 backend 代理（仅网络类错误；登录接口禁止自动回退，避免误报密码错误） */
cloudMembershipApi.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error?.config as any;
    const reqPath = String(config?.url || "");
    if (/\/auth\/login\b/i.test(reqPath)) {
      return Promise.reject(error);
    }
    if (!isDesktopClient() || config?.__localProxyFallback) {
      return Promise.reject(error);
    }
    if (!isMembershipNetworkFailure(error)) {
      return Promise.reject(error);
    }
    // 禁止回退本地：管理员写操作、财务写操作（避免 cloud/local 双账本或 user_id 错位）
    const method = String(config?.method || "get").toLowerCase();
    const isMutating = ["post", "put", "patch", "delete"].includes(method);
    const noLocalProxy =
    isMutating &&
    /\/(recharge\/create|vip\/redeem|withdraw\/apply|recharge\/mock-paid|pay\/callback|admin\/withdraw\/(approve|reject|batch-review)|admin\/users\/create)\b/i.test(reqPath);
  
    if (noLocalProxy) {
      return Promise.reject(error);
    }
    config.__localProxyFallback = true;
    try {
      const hdrCfg = attachMembershipRequestHeaders({ headers: { ...(config.headers || {}) } });
      const resp = await axios.request({
        method: config.method,
        url: config.url,
        params: config.params,
        data: config.data,
        headers: (hdrCfg as any).headers,
        baseURL: `${getBackendHttpBase()}/api/membership`,
        timeout: Math.max(Number(config.timeout) || 60000, 60000),
      });
      return resp;
    } catch (localErr) {
      return Promise.reject(localErr);
    }
  }
);

api.interceptors.response.use((response) => response.data, handleApiResponseError);
cloudMembershipApi.interceptors.response.use((response) => response.data, handleApiResponseError);

// ===================== 配置管理 API =====================

const CONFIG_CACHE_KEY = "app_config_cache_v1";

function readConfigCacheFromStorage() {
  try {
    const raw = localStorage.getItem(CONFIG_CACHE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function writeConfigCacheToStorage(value: any) {
  try {
    if (!value) return;
    localStorage.setItem(CONFIG_CACHE_KEY, JSON.stringify(value));
  } catch {
    // ignore
  }
}

let configCache: any = readConfigCacheFromStorage();
let configPrimePromise: Promise<any> | null = null;
let configRevalidatePromise: Promise<any> | null = null;
const configUpdateListeners = new Set<() => void>();

export function subscribeConfigUpdates(listener: () => void): () => void {
  configUpdateListeners.add(listener);
  return () => configUpdateListeners.delete(listener);
}

function notifyConfigUpdates() {
  configUpdateListeners.forEach((fn) => {
    try {
      fn();
    } catch {
      // ignore
    }
  });
}

function unwrapConfigRoot(raw: any): Record<string, any> | null {
  if (!raw || typeof raw !== "object") return null;
  const data = (raw as Record<string, unknown>).data;
  if (data && typeof data === "object" && !Array.isArray(data)) {
    return data as Record<string, any>;
  }
  return raw as Record<string, any>;
}

function getSectionFromCache(section: string): any | undefined {
  const root = unwrapConfigRoot(configCache);
  if (!root) return undefined;
  return root[section];
}

function mergeSectionIntoCache(section: string, sectionData: any) {
  const prevRoot = unwrapConfigRoot(configCache) || {};
  const nextRoot = { ...prevRoot, [section]: sectionData };
  const wrapped =
    configCache && typeof configCache === "object" && "success" in configCache
      ? { ...configCache, success: true, data: nextRoot }
      : { success: true, data: nextRoot };
  configCache = wrapped;
  writeConfigCacheToStorage(wrapped);
  notifyConfigUpdates();
}

const sectionFetchPromises = new Map<string, Promise<any>>();

async function fetchConfigSection(section: string, forceRefresh: boolean = false) {
  const cached = !forceRefresh ? getSectionFromCache(section) : undefined;
  if (cached !== undefined) return cached;

  const inflight = sectionFetchPromises.get(section);
  if (!forceRefresh && inflight) return inflight;

  const promise = api
    .get(`/config/section/${encodeURIComponent(section)}`, {
      timeout: isDesktopClient() ? 10000 : 20000,
    })
    .then((res: any) => {
      const data = res?.data ?? res;
      mergeSectionIntoCache(section, data);
      return data;
    })
    .catch((err) => {
      const stale = getSectionFromCache(section);
      if (stale !== undefined) return stale;
      throw err;
    })
    .finally(() => {
      sectionFetchPromises.delete(section);
    });

  sectionFetchPromises.set(section, promise);
  return promise;
}

let _lastRevalidateAt = 0;
function revalidateConfigInBackground(): Promise<any> | null {
  const _now = Date.now();
  if (_now - _lastRevalidateAt < 30000) return null;
  
  if (configRevalidatePromise) return configRevalidatePromise;
  _lastRevalidateAt = _now;
  configRevalidatePromise = api
    .get("/config/", { timeout: isDesktopClient() ? 15000 : 30000 })
    .then((latest) => {
      configCache = latest;
      writeConfigCacheToStorage(latest);
      notifyConfigUpdates();
      return latest;
    })
    .catch(() => configCache)
    .finally(() => {
      configRevalidatePromise = null;
    });
  return configRevalidatePromise;
}

/** 云端管理员配置 pull：单飞 + 短冷却，避免登录/轮询/页面并发写 config */
let cloudPullInFlight: Promise<unknown> | null = null;
let lastCloudPullFinishedAt = 0;
const CLOUD_PULL_COOLDOWN_MS = 2500;

async function pullCloudAdminRuntimeOnce(): Promise<unknown> {
  const saved = await api.post("/config/pull-cloud-admin-runtime", {}, withAdminConfig());
  await configApi.refreshFromServer().catch(() => undefined);
  lastCloudPullFinishedAt = Date.now();
  return saved;
}

export async function pullCloudAdminRuntimeCoordinated(opts?: { force?: boolean }): Promise<unknown | null> {
  if (!isDesktopClient() || !getMembershipToken()) return null;
  const force = !!opts?.force;
  const now = Date.now();
  if (cloudPullInFlight) return cloudPullInFlight;
  if (!force && lastCloudPullFinishedAt && now - lastCloudPullFinishedAt < CLOUD_PULL_COOLDOWN_MS) {
    return null;
  }
  cloudPullInFlight = pullCloudAdminRuntimeOnce().finally(() => {
    cloudPullInFlight = null;
  });
  return cloudPullInFlight;
}

let stopCloudAdminConfigWatcher: (() => void) | null = null;

/** 桌面端统一：登录后 pull + 按云端 revision 轮询（App 仅此一处启动） */
export function startCloudAdminConfigWatcher(active: boolean): void {
  if (stopCloudAdminConfigWatcher) {
    stopCloudAdminConfigWatcher();
    stopCloudAdminConfigWatcher = null;
  }
  if (!active || !isDesktopClient()) return;

  let lastRev = 0;
  const tick = async () => {
    if (!getMembershipToken()) return;
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
    try {
      const revRes: any = await configApi.getCloudAdminRevision();
      const payload = revRes?.data ?? revRes;
      if (String(payload?.source || "").trim() !== "cloud") return;
      const rev = Number(payload?.revision ?? 0);
      if (!rev || rev === lastRev) return;
      lastRev = rev;
      await pullCloudAdminRuntimeCoordinated({ force: true });
    } catch {
      // ignore
    }
  };

  void pullCloudAdminRuntimeCoordinated({ force: true });
  void tick();
  const timer = window.setInterval(tick, 120000);
  stopCloudAdminConfigWatcher = () => window.clearInterval(timer);
}

export const configApi = {
  /** 获取当前配置（优先内存缓存；失败时回退本地缓存，避免页面数据被清空） */
  get: async (forceRefresh: boolean = false) => {
    if (!forceRefresh && configCache) {
      void revalidateConfigInBackground();
      return configCache;
    }

    if (!forceRefresh && configPrimePromise) {
      const primed = await configPrimePromise;
      if (primed) return primed;
    }

    try {
      const latest = await api.get("/config/", { timeout: isDesktopClient() ? 15000 : 30000 });
      configCache = latest;
      writeConfigCacheToStorage(latest);
      notifyConfigUpdates();
      return latest;
    } catch (err) {
      const stale = configCache || readConfigCacheFromStorage();
      if (stale) return stale;
      throw err;
    }
  },

  /** 后台刷新配置（不阻塞调用方） */
  revalidateInBackground: () => {
    void revalidateConfigInBackground();
  },

  /** 应用启动时预热配置缓存（可等待，确保进系统后配置即就绪） */
  prime: async (waitReady: boolean = false) => {
    if (configCache && !waitReady) return configCache;

    if (!configPrimePromise) {
      configPrimePromise = (async () => {
        const desktop = isDesktopClient();
        const maxRounds = waitReady ? (desktop ? 4 : 6) : 2;
        const configTimeoutMs = desktop ? 5000 : 30000;
        for (let i = 0; i < maxRounds; i++) {
          try {
            const latest = await api.get("/config/", { timeout: configTimeoutMs });
            configCache = latest;
            writeConfigCacheToStorage(latest);
            notifyConfigUpdates();
            return latest;
          } catch {
            // 有本地缓存时不阻塞首屏
            if (configCache && !waitReady) return configCache;
            await sleep(waitReady ? (desktop ? 300 : 450) : 220);
          }
        }
        return configCache || null;
      })().finally(() => {
        configPrimePromise = null;
      });
    }

    return await configPrimePromise;
  },

  /** 读取当前缓存（不发请求） */
  getCached: () => configCache,

  /** 读取已解包配置根对象（不发请求） */
  getConfigRootSync: () => unwrapConfigRoot(configCache),

  /** 获取单个配置段（优先缓存；比全量 GET /config/ 更快） */
  getSection: (section: string, forceRefresh: boolean = false) =>
    fetchConfigSection(section, forceRefresh),

  /** 并行获取多个配置段（仅请求缓存中缺失的段） */
  getSections: async (sections: string[], forceRefresh: boolean = false) => {
    const result: Record<string, any> = {};
    const missing: string[] = [];
    for (const section of sections) {
      const cached = !forceRefresh ? getSectionFromCache(section) : undefined;
      if (cached !== undefined) {
        result[section] = cached;
      } else {
        missing.push(section);
      }
    }
    if (missing.length) {
      const fetched = await Promise.all(
        missing.map(async (section) => {
          const data = await fetchConfigSection(section, forceRefresh);
          return [section, data] as const;
        }),
      );
      for (const [section, data] of fetched) {
        result[section] = data;
      }
    }
    return result;
  },

  /** 更新单个配置段（返回全量配置并刷新缓存） */
  updateSection: async (section: string, body: Record<string, any>) => {
    const saved = await api.put(
      `/config/section/${encodeURIComponent(section)}`,
      body,
      withAdminConfig(),
    );
    configCache = saved;
    writeConfigCacheToStorage(saved);
    notifyConfigUpdates();
    return saved;
  },

  /** 标记配置需重新拉取（保留 localStorage 作 stale 回退，避免清空后各页读不到路径） */
  invalidateCache: () => {
    configCache = null;
  },

  /**
   * 直接将分组发品链接写入前端缓存并触发页面重渲染
   * 用于登录成功后直接更新分组数据，不依赖 GET /api/config/（该接口可能被会员限制）
   */
  patchGroupUrlMap: (groupUrlMap: Record<string, string>) => {
    try {
      if (!groupUrlMap || typeof groupUrlMap !== "object") return;
      const keys = Object.keys(groupUrlMap);
      if (keys.length === 0) return;
      // 更新内存缓存
      if (configCache) {
        const root = (configCache as any)?.data ?? configCache;
        if (root && typeof root === "object") {
          if (!root.group_urls || typeof root.group_urls !== "object") root.group_urls = {};
          root.group_urls.group_url_map = { ...groupUrlMap };
        }
      }
      // 同步写入 localStorage
      writeConfigCacheToStorage(configCache);
      // 触发所有订阅者重新读取缓存（如 ProductConfig.tsx 中的 loadConfig）
      notifyConfigUpdates();
    } catch {
      // ignore
    }
  },

  /** 云端拉取后刷新内存/本地配置缓存 */
  refreshFromServer: async () => {
    try {
      const latest = await api.get("/config/", { timeout: 30000 });
      configCache = latest;
      writeConfigCacheToStorage(latest);
      notifyConfigUpdates();
      return latest;
    } catch (err) {
      const stale = configCache || readConfigCacheFromStorage();
      if (stale) return stale;
      throw err;
    }
  },

  /** 从云端拉取管理员配置到本机并刷新前端缓存（内部走协调器去重） */
  pullCloudAdminRuntime: () => pullCloudAdminRuntimeCoordinated({ force: false }),

  /**
   * 启动 AI 功能前：本机后端用内置 admin key 从总部拉 Key（不返回明文给浏览器）。
   */
  ensureRuntimeSecrets: () =>
    api.post("/config/ensure-runtime-secrets", {}, { ...withAdminConfig(), timeout: 60000 }),

  /** 配置 revision（检测其他客户端是否已保存） */
  getRevision: () => api.get("/config/revision"),

  /** 云端管理员配置 revision（全客户端统一） */
  getCloudAdminRevision: () => api.get("/config/cloud-admin-revision"),

  /** 管理员运行时配置（Key / 模型等） */
  getAdminRuntime: () => api.get("/config/admin-runtime"),

  /** 更新配置 */
  update: async (data: Record<string, any>) => {
    const saved = await api.put("/config/", data, withAdminConfig());
    configCache = saved;
    writeConfigCacheToStorage(saved);
    notifyConfigUpdates();
    return saved;
  },

  /** 获取配置模板 */
  getTemplate: () => api.get("/config/template"),

  /** 重置为默认配置 */
  reset: () => api.post("/config/reset"),

  /** 保存桌面端采集到的 cookies 到配置的 cookie_file */
  saveCookiesFromDesktop: (payload: { cookies: Array<Record<string, any>>; source_url?: string }) =>
    api.post("/config/cookie/save-from-desktop", payload),

  /** 复用自动发品同款登录流程（BrowserManager），登录后自动保存 cookie */
  loginCookieByBrowserManager: () =>
    api.post("/config/cookie/login-by-browser-manager", {}, { timeout: 360000 }),

  /** 从平台URL + Cookie抓取属性并写入属性配置 */
  fetchAttributesFromPlatform: () =>
    api.post("/config/attributes/fetch-from-platform", {}, { timeout: 360000 }),

  /** 从分组发品链接 + Cookie抓取商品规格并写入规格配置 */
  fetchSpecificationsFromPlatform: () =>
    api.post("/config/specifications/fetch-from-platform", {}, { timeout: 360000 }),
};

// ===================== 产品上传 API =====================

export const uploadApi = {
  /** 启动自动发品任务 */
  start: (params?: { mode?: "batch" | "single" | "scheduled" | "daily_scheduled" | string; max_products?: number; scheduled_time?: string }) =>
    api.post("/upload/start", params || {}),

  /** 停止发品任务 */
  stop: () => api.post("/upload/stop"),

  /** 暂停发品任务 */
  pause: () => api.post("/upload/pause"),

  /** 恢复发品任务 */
  resume: () => api.post("/upload/resume"),

  /** 获取任务状态 */
  getStatus: () => api.get("/upload/status"),

  /** 获取可发布产品列表 */
  getAvailable: () => api.get("/upload/products/available"),

  /** 获取已发布产品列表 */
  getPublished: () => api.get("/upload/products/published"),

  /** 启动优化产品任务 */
  startOptimize: (params?: { manual_product_ids?: string }) =>
    api.post("/upload/optimize/start", params || {}),

  /** 停止优化产品任务 */
  stopOptimize: () => api.post("/upload/optimize/stop"),

  /** 获取优化产品任务状态 */
  getOptimizeStatus: () => api.get("/upload/optimize/status"),

  /** 获取优化产品列表 */
  getOptimizeList: (params?: { limit?: number }) => api.get("/upload/optimize/list", { params: params || {} }),

  /** 删除优化产品记录 */
  deleteOptimizeRecord: (params: { product_id: string; optimize_date?: string }) =>
    api.post("/upload/optimize/delete", params),

  /** 获取当天失败的优化产品ID */
  getOptimizeFailedToday: () => api.get("/upload/optimize/failed-today"),
};

// ===================== 发品页扫描 API（独立工具） =====================

export const pageScanApi = {
  /** 扫描单个发品页面交互元素 */
  scan: (params: { url: string; probe_buttons?: boolean; wait_seconds?: number }) =>
    api.post("/page-scan/scan", params, { timeout: 300000 }),

  /** 批量扫描多个发品页面（复用浏览器会话） */
  scanBatch: (params: {
    pages: { name?: string; url: string }[];
    probe_buttons?: boolean;
    wait_seconds?: number;
  }) => api.post("/page-scan/scan-batch", params, { timeout: 900000 }),

  /** 将扫描结果应用到产品配置（对接自动发品） */
  applyToConfig: (params: {
    group_name: string;
    url: string;
    workflows?: Record<string, unknown>[];
    page_type?: string;
    page_type_label?: string;
    element_count?: number;
    workflow_count?: number;
    sync_platform?: boolean;
  }) => api.post("/page-scan/apply-to-config", params, { timeout: 600000 }),

  /** 验收：检查组别发品就绪状态 */
  validateGroup: (groupName: string) =>
    api.get(`/page-scan/validate-group/${encodeURIComponent(groupName)}`),
};

// ===================== 图片管理 API =====================

export const videoBindApi = {
  /** 启动新品绑定视频任务 */
  start: (params?: { video_per_product_limit?: number; max_linked_count?: number }) =>
    api.post("/video-bind/start", params || {}),

  /** 停止任务 */
  stop: () => api.post("/video-bind/stop"),

  /** 暂停任务 */
  pause: () => api.post("/video-bind/pause"),

  /** 恢复任务 */
  resume: () => api.post("/video-bind/resume"),

  /** 获取任务状态 */
  getStatus: () => api.get("/video-bind/status"),

  /** 获取新品绑定视频数据预览 */
  getNewLinksPreview: () => api.get("/video-bind/new-links-preview"),
};

// ===================== 图片管理 API =====================

export const imageApi = {
  /** 获取图片分组列表 */
  getGroups: () => api.get("/images/groups"),

  /** 获取指定分组的图片 */
  getGroupImages: (groupId: string) => api.get(`/images/group/${groupId}`),

  /** 获取图片统计 */
  getStats: () => api.get("/images/stats"),

  /** 获取图片规范化配置 */
  getConfig: () => api.get("/images/config"),

  /** 更新图片规范化配置 */
  updateConfig: (data: Record<string, any>) => api.put("/images/config", data),

  /** 启动图片规范化任务 */
  startNormalize: (payload?: { source_dirs?: string[] }) => api.post("/images/normalize/start", payload || {}),

  /** 获取规范化任务状态 */
  getNormalizeStatus: () => api.get("/images/normalize/status"),

  /** 停止图片规范化任务 */
  stopNormalize: () => api.post("/images/normalize/stop"),

  /** 获取最近图片规范化日志（后端缓冲区） */
  getRecentLogs: (limit: number = 500) => api.get("/images/logs/recent", { params: { limit } }),

  /** 获取图片文件（二进制，携带鉴权头） */
  getImageFileBlob: (path: string) =>
    api.get("/images/file", {
      params: { path },
      responseType: "blob",
    }),

  /** 生成图片文件访问URL */
  getImageFileUrl: (path: string) => `${API_BASE}/images/file?path=${encodeURIComponent(path)}`,

  /** AI 生图配置 */
  getAiGenConfig: () => api.get("/images/ai-gen/config"),
  updateAiGenConfig: (data: Record<string, any>) => api.put("/images/ai-gen/config", data),
  getAiGenInputs: () => api.get("/images/ai-gen/inputs"),
  getAiGenOutputs: (product?: string) => api.get("/images/ai-gen/outputs", { params: product ? { product } : {} }),
  getAiGenPrompts: (imagePath: string) => api.get("/images/ai-gen/prompts", { params: { image_path: imagePath } }),
  getAiGenPointsPricing: () => api.get("/images/ai-gen/points-pricing"),
  getAiGenPointsEstimate: () => api.get("/images/ai-gen/points-estimate"),
  getAiGenRecentLogs: (limit?: number) =>
    api.get("/images/ai-gen/logs/recent", { params: limit ? { limit } : {} }),
  startAiGen: () => api.post("/images/ai-gen/start"),
  getAiGenStatus: () => api.get("/images/ai-gen/status"),
  stopAiGen: () => api.post("/images/ai-gen/stop"),
};

// ===================== 数据下载 API =====================

export const dataApi = {
  /** 启动数据下载任务 */
  startDownload: (params: {
    task_type: string;
    date_range?: string;
    period_type?: string;
    big_keywords?: string;
    dropdown_keywords?: string;
  }) => api.post("/data/download/start", params),

  /** 停止下载任务 */
  stopDownload: (taskType: string) => api.post(`/data/download/stop/${taskType}`),

  /** 获取下载任务状态 */
  getDownloadStatus: (taskType: string) => api.get(`/data/download/status/${taskType}`),

  /** 获取所有下载任务状态 */
  getAllDownloadStatus: () => api.get("/data/download/status"),

  /** 获取已下载文件列表 */
  getFiles: (dirPath?: string) =>
    api.get("/data/files", { params: dirPath ? { dir_path: dirPath } : {} }),

  /** 获取关键词最新异动 */
  getKeywordLatestAnomaly: (dirPath?: string) =>
    api.get("/data/keyword/anomaly/latest", { params: dirPath ? { dir_path: dirPath } : {} }),

  /** 获取关键词汇总最新值 */
  getKeywordLatestSummary: (dirPath?: string) =>
    api.get("/data/keyword/summary/latest", { params: dirPath ? { dir_path: dirPath } : {} }),

  /** 获取行业关键词整合结果（按最新日期列降序） */
  getIndustryKeywordLatest: (outputFile?: string) =>
    api.get("/data/industry-keyword/latest", { params: outputFile ? { output_file: outputFile } : {} }),

  /** 获取行业关键词下拉词结果表 */
  getIndustryKeywordDropdownLatest: (outputFile?: string) =>
    api.get("/data/industry-keyword/dropdown/latest", { params: outputFile ? { output_file: outputFile } : {} }),

  /** 删除行业关键词整合表中的关键词 */
  deleteIndustryKeywordRows: (keywords: string[], outputFile?: string) =>
    api.post("/data/industry-keyword/delete", { keywords, ...(outputFile ? { output_file: outputFile } : {}) }),

  /** 删除行业关键词下拉词表中的行（原词+下拉词） */
  deleteIndustryKeywordDropdownRows: (rows: Array<{ 原词: string; 下拉词: string }>, outputFile?: string) =>
    api.post("/data/industry-keyword/dropdown/delete", { rows, ...(outputFile ? { output_file: outputFile } : {}) }),

  /** 行业关键词/下拉词调用AI生成标题 */
  startIndustryKeywordTitleGenerate: (params: {
    mode: "industry_hot" | "dropdown";
    scenes: string;
    material?: string;
    titles_per_scene: number;
    keywords?: string[];
    output_file?: string;
    dropdown_output_file?: string;
  }) => api.post("/data/industry-keyword/title/generate/start", params),
  getIndustryKeywordTitleGenerateStatus: () => api.get("/data/industry-keyword/title/generate/status"),
  stopIndustryKeywordTitleGenerate: () => api.post("/data/industry-keyword/title/generate/stop", {}),
  getIndustryKeywordTitleGenerateResult: () => api.get("/data/industry-keyword/title/generate/result"),

  /** 获取店铺运营最新数据 */
  getStoreOverviewLatest: (savePath?: string, includeDetails: boolean = true) =>
    api.get("/data/store/overview/latest", {
      params: {
        ...(savePath ? { save_path: savePath } : {}),
        include_details: includeDetails,
      },
    }),

  /** 获取店铺周汇总表格（默认“总结”sheet） */
  getStoreSummaryTable: (filePath?: string, sheetName?: string) =>
    api.get("/data/store/summary/table", {
      params: {
        ...(filePath ? { file_path: filePath } : {}),
        ...(sheetName ? { sheet_name: sheetName } : {}),
      },
    }),

  /** 获取产品360 Excel结果表格（默认“产品详细信息”sheet） */
  getProduct360Table: (outputDir?: string, sheetName?: string) =>
    api.get("/data/product360/table", {
      params: {
        ...(outputDir ? { output_dir: outputDir } : {}),
        ...(sheetName ? { sheet_name: sheetName } : {}),
      },
    }),

  /** 获取产品360「流量来源」最新日期渠道访问人数（按产品ID筛选，P4P渠道表用） */
  getProduct360TrafficChannels: (outputDir?: string, productIds?: string[]) =>
    api.post("/data/product360/traffic-channels", {
      ...(outputDir ? { output_dir: outputDir } : {}),
      product_ids: Array.isArray(productIds) ? productIds : [],
    }),

  /** 获取产品运营下载结果表格 */
  getProductOperateTable: (filePath?: string) =>
    api.get("/data/product-operate/table", {
      params: {
        ...(filePath ? { file_path: filePath } : {}),
      },
    }),

  /** 获取流量渠道总览（当天/本周/本月/分析结果） */
  getTrafficChannelOverview: (filePath?: string, sheetName?: string) =>
    api.get("/data/traffic-channel/overview", {
      params: {
        ...(filePath ? { file_path: filePath } : {}),
        ...(sheetName ? { sheet_name: sheetName } : {}),
      },
    }),

  /** 获取店铺图片采集列表 */
  getStoreImageList: (saveDir?: string, keyword?: string) =>
    api.get("/data/store-image/list", {
      params: {
        ...(saveDir ? { save_dir: saveDir } : {}),
        ...(keyword ? { keyword } : {}),
      },
    }),

  /** 获取店铺图片文件（二进制，携带鉴权头） */
  getStoreImageFileBlob: (path: string) =>
    api.get("/data/store-image/file", {
      params: { path },
      responseType: "blob",
    }),

};

// ===================== 数据分析 API =====================

export const analysisApi = {
  /** 启动分析任务 */
  start: (params: { task_type: string; source_file?: string }) =>
    api.post("/analysis/start", params, { ...withAdminConfig(), timeout: 120000 }),

  getPointsPricing: () => api.get("/analysis/points-pricing", withAdminConfig()),

  getTitleOptimizePointsEstimate: (sourceFile?: string) =>
    api.get("/analysis/title-optimize/points-estimate", withAdminConfig({
      params: sourceFile ? { source_file: sourceFile } : {},
      timeout: 120000,
    })),

  getTrafficAiPointsEstimate: () =>
    api.get("/analysis/traffic-ai/points-estimate", { ...withAdminConfig(), timeout: 120000 }),

  /** 开始分析前检查标题优化输入是否齐全 */
  inspectTitleOptimizeInputs: (params: { task_type: string; source_file?: string }) =>
    api.post("/analysis/inspect/title-optimize-inputs", params, { ...withAdminConfig(), timeout: 120000 }),

  /** 获取流量波动异动（正负分组） */
  getVolatilityAnomaly: (filePath?: string) =>
    api.get("/analysis/volatility/anomaly", withAdminConfig({ params: filePath ? { file_path: filePath } : {}, timeout: 120000 })),

  /** 获取新发链接监控表 */
  getNewLinksMonitor: (filePath?: string, sheetName?: string) =>
    api.get("/analysis/new-links/monitor", withAdminConfig({ params: { ...(filePath ? { file_path: filePath } : {}), ...(sheetName ? { sheet_name: sheetName } : {}) }, timeout: 120000 })),

  /** 获取诊断表 */
  getDiagnosisTable: (filePath?: string) =>
    api.get("/analysis/diagnosis/table", withAdminConfig({ params: filePath ? { file_path: filePath } : {}, timeout: 120000 })),

  /** 获取统计输出表（统计csss.xlsx） */
  getStatisticsTable: (filePath?: string, sheetName?: string) =>
    api.get("/analysis/statistics/table", withAdminConfig({ params: { ...(filePath ? { file_path: filePath } : {}), ...(sheetName ? { sheet_name: sheetName } : {}) }, timeout: 120000 })),

  /** 获取P4P输出表（P4P数据统计.xlsx） */
  getP4pTable: (filePath?: string, sheetName?: string) =>
    api.get("/analysis/p4p/table", withAdminConfig({ params: { ...(filePath ? { file_path: filePath } : {}), ...(sheetName ? { sheet_name: sheetName } : {}) }, timeout: 120000 })),

  /** 获取产品优化建议结果 */
  getTitleOptimizeResults: () => api.get("/analysis/title-optimize/results", { ...withAdminConfig(), timeout: 120000 }),

  /** 获取产品优化建议详情 */
  getTitleOptimizeDetail: (productId: string) =>
    api.get("/analysis/title-optimize/detail", withAdminConfig({ params: { product_id: productId }, timeout: 120000 })),

  /** 获取店铺整体数据AI分析结果 */
  getTrafficAiResult: () => api.get("/analysis/traffic-ai/result", { ...withAdminConfig(), timeout: 120000 }),

  /** 停止分析任务 */
  stop: (taskType: string) => api.post(`/analysis/stop/${taskType}`, {}, withAdminConfig()),

  /** 获取分析任务状态 */
  getStatus: (taskType: string) => api.get(`/analysis/status/${taskType}`, { ...withAdminConfig(), timeout: 60000 }),

  /** 获取分析结果 */
  getResults: (taskType: string) => api.get(`/analysis/results/${taskType}`, { ...withAdminConfig(), timeout: 120000 }),

  /** 获取数据概览 */
  getOverview: () => api.get("/analysis/overview", { ...withAdminConfig(), timeout: 120000 }),
};

// ===================== 任务管理 API =====================

export const membershipApi = {
  register: (params: { username: string; password: string; shop_url?: string | null; invite_code?: string | null }) =>
    cloudMembershipApi.post("/auth/register", params),

  /** 开发环境管理员：走本地 admin_accounts */
  adminLogin: (params: { username: string; password: string }) =>
    api.post("/membership/auth/admin-login", params, { timeout: 8000 }),

  adminAgentRegister: (params: { agent_id: string; client_name?: string; machine_id?: string; app_version?: string; license_key?: string }, adminKey: string) =>
    cloudMembershipApi.post("/agent/register", params, { headers: { "X-Admin-Key": adminKey } }),
  
  adminAgentHeartbeat: (params: { agent_id: string; status?: string }, adminKey: string) =>
    cloudMembershipApi.post("/agent/heartbeat", params, { headers: { "X-Admin-Key": adminKey } }),
  

  /** 关键词汇总回传：走云端入库，确保管理员在云端能查询到数据 */
  telemetryKeywords: (params: {
    agent_id: string;
    report_date: string;
    batch_no: string;
    source?: string;
    items: Array<{ keyword: string; exposure?: number; click?: number; ctr?: number; keyword_index?: number; product_id?: string }>;
  }) => cloudMembershipApi.post("/telemetry/keywords", params),


  login: (params: { username: string; password: string }) =>
    cloudMembershipApi.post("/auth/login", params),

  /** 桌面端诊断：云端连通性（假 DNS / IP 回退是否生效） */
  connectivity: () => api.get("/membership/connectivity", { timeout: 20000 }),

  /**
   * 统一登录：桌面端优先云端（会员），再本机（管理员）；开发环境先本机再云端。
   */
  loginUnified: async (params: { username: string; password: string }) => {
    const creds = {
      username: String(params.username || "").trim(),
      password: String(params.password || "").trim(),
    };
    const unwrap = (res: unknown): Record<string, unknown> => {
      const r = res as { data?: Record<string, unknown> };
      return (r?.data !== undefined ? r.data : (res as Record<string, unknown>)) || {};
    };
    const isAuthError = (msg: string) =>
      /账号或密码|管理员账号|密码错误|invalid credentials/i.test(msg);
    const isCloudUnavailable = (msg: string) =>
      /云端会员服务暂不可用|不可达|VPN|Clash|假 DNS|DoH|SSL|EOF|handshake|UNEXPECTED|超时|timeout|ALI_OFFLINE_DEV/i.test(
        msg
      );

    const tryLocal = async (opts?: { skipWait?: boolean; timeout?: number }) => {
      if (isDesktopClient() && !opts?.skipWait) {
        await waitLocalBackendReady(30000);
      }
      const local = await api.post("/membership/auth/login", creds, {
        timeout: opts?.timeout ?? 90000,
      });
      return unwrap(local);
    };

    const ensureMemberRole = (data: Record<string, unknown>) => {
      if (!data.role) data.role = "member";
      return data;
    };

    const tryCloud = async () => {
      const cloud = await cloudMembershipApi.post("/auth/login", creds, { timeout: 90000 });
      return ensureMemberRole(unwrap(cloud));
    };

    if (isDesktopClient()) {
      const ready = await waitLocalBackendReady(15000);
      if (!ready) {
        throw new Error(
          "本地服务未启动完成，无法登录。请关闭软件后重新打开，等待约 30 秒再试；仍失败请联系技术支持并提供 runtime.log"
        );
      }

      let cloudAuthErr: unknown = null;
      try {
        const data = await tryLocal({ skipWait: true, timeout: 15000 });
        if (data.role) return data;
        throw new Error("登录响应异常：未返回 role");
      } catch (localErr: unknown) {
        const localMsg = String((localErr as Error)?.message || "");
        if (isAuthError(localMsg)) {
          cloudAuthErr = localErr;
        } else {
          // 本机代理云端失败时，再试渲染进程直连（Electron host-resolver 规则）
          try {
            const data = await tryCloud();
            if (data.role) return data;
          } catch (cloudErr: unknown) {
            const cloudMsg = String((cloudErr as Error)?.message || "");
            if (isAuthError(cloudMsg)) throw cloudErr;
            throw localErr;
          }
        }
      }

      if (cloudAuthErr) throw cloudAuthErr;
      throw new Error("登录失败，请检查账号密码或网络");
    }

    try {
      const data = await tryLocal();
      if (data.role) return data;
    } catch (e: unknown) {
      const msg = String((e as Error)?.message || "");
      if (isAuthError(msg)) throw e;
      // 本机已判定云端不可达时，不再走 Vite /cloud-api（避免误报 500）
      if (isCloudUnavailable(msg)) throw e;
    }
    return await tryCloud();
  },

  /** 云端登录成功后，将会话同步到本地后端（仅本地 /api） */
  syncLocalSession: () => api.post("/membership/auth/sync-local-session", {}, { timeout: 10000 }),

  /** 管理员向本机申请 Bearer token（与 X-Admin-Key 配合） */
  syncAdminSession: () =>
    api.post("/membership/auth/sync-admin-session", {}, { timeout: 8000 }),

  /** 管理员 Bearer 会话：从本机 backend 刷新有效的 admin_key（避免 localStorage 缓存占位符） */
  refreshAdminSessionKey: () => api.get("/membership/auth/admin-session-key", { timeout: 10000 }),

  me: () => cloudMembershipApi.get("/me", { timeout: 20000 }),

  ledger: (limit: number = 50) =>
    cloudMembershipApi.get("/points/ledger", { params: { limit } }),
  
  
  createRecharge: (params: { channel: "wechat" | "alipay"; amount_yuan: number }) =>
    cloudMembershipApi.post("/recharge/create", params),

  mockPaid: (order_no: string) => cloudMembershipApi.post("/recharge/mock-paid", { order_no }),

  callbackWechat: (payload: Record<string, any>) => cloudMembershipApi.post("/pay/callback/wechat", payload),

  callbackAlipay: (payload: Record<string, any>) => cloudMembershipApi.post("/pay/callback/alipay", payload),

  getRechargeOrder: (order_no: string) => cloudMembershipApi.get(`/recharge/order/${order_no}`),

  listRechargeOrders: (params?: { status?: string; limit?: number }) =>
    cloudMembershipApi.get("/recharge/list", { params: params || {} }),

  listRechargeOrdersPaged: (params?: { status?: string; page?: number; page_size?: number }) =>
    useLocalMembershipProxy()
      ? api.get("/membership/recharge/list-paged", { params: params || {}, timeout: 15000 })
      : cloudMembershipApi.get("/recharge/list-paged", { params: params || {} }),

  redeemVip: (months: number = 1) => cloudMembershipApi.post("/vip/redeem", { months }),

  applyWithdraw: (params: { points: number; channel: string; account: string }) =>
    cloudMembershipApi.post("/withdraw/apply", params),

  adminListWithdraw: (params?: { status?: string; limit?: number; adminKey?: string }) =>
    cloudMembershipApi.get("/admin/withdraw/list", {
      params: params?.status || params?.limit ? { status: params?.status, limit: params?.limit } : {},
      headers: params?.adminKey ? { "X-Admin-Key": params.adminKey } : {},
    }),

  adminApproveWithdraw: (withdraw_no: string, adminKey: string) =>
    cloudMembershipApi.post("/admin/withdraw/approve", { withdraw_no }, { headers: { "X-Admin-Key": adminKey } }),

  adminRejectWithdraw: (withdraw_no: string, reason: string, adminKey: string) =>
    cloudMembershipApi.post("/admin/withdraw/reject", { withdraw_no, reason }, { headers: { "X-Admin-Key": adminKey } }),

  adminBatchReviewWithdraw: (params: { withdraw_nos: string[]; action: "approve" | "reject"; reason?: string }, adminKey: string) =>
    cloudMembershipApi.post("/admin/withdraw/batch-review", params, { headers: { "X-Admin-Key": adminKey } }),

  adminDashboard: (days: number, adminKey: string) =>
    cloudMembershipApi.get("/admin/dashboard", { params: { days }, headers: { "X-Admin-Key": adminKey } }),

  adminUsers: (params: { limit?: number; adminKey: string }) =>
    cloudMembershipApi.get("/admin/users", {
      params: params?.limit ? { limit: params.limit } : {},
      headers: { "X-Admin-Key": params.adminKey },
    }),

  adminUserCreate: (params: {
    username: string;
    password: string;
    real_name?: string;
    phone?: string;
    invite_code?: string;
    points_balance?: number;
    trial_days?: number;
    adminKey: string;
  }) =>
    cloudMembershipApi.post(
      "/admin/users/create",
      {
        username: params.username,
        password: params.password,
        real_name: params.real_name || "",
        phone: params.phone || "",
        invite_code: params.invite_code || null,
        points_balance: Number(params.points_balance || 0),
        trial_days: Number(params.trial_days || 15),
      },
      { headers: { "X-Admin-Key": params.adminKey } }
    ),

  adminUserDelete: (params: { user_id: number; adminKey: string }) =>
    cloudMembershipApi.post("/admin/users/delete", { user_id: params.user_id }, { headers: { "X-Admin-Key": params.adminKey } }),

  adminUserControl: (params: { user_id: number; mode: "normal" | "force_allow" | "force_block"; note?: string; adminKey: string }) =>
    cloudMembershipApi.post(
      "/admin/users/control",
      { user_id: params.user_id, mode: params.mode, note: params.note || "" },
      { headers: { "X-Admin-Key": params.adminKey } }
    ),

  adminUserUpdate: (params: {
    user_id: number;
    password?: string;
    points_balance?: number;
    trial_start_at?: string;
    trial_end_at?: string;
    vip_expire_at?: string;
    adminKey: string;
  }) =>
    cloudMembershipApi.post(
      "/admin/users/update",
      {
        user_id: params.user_id,
        ...(params.password !== undefined ? { password: params.password } : {}),
        ...(params.points_balance !== undefined ? { points_balance: params.points_balance } : {}),
        ...(params.trial_start_at !== undefined ? { trial_start_at: params.trial_start_at } : {}),
        ...(params.trial_end_at !== undefined ? { trial_end_at: params.trial_end_at } : {}),
        ...(params.vip_expire_at !== undefined ? { vip_expire_at: params.vip_expire_at } : {}),
      },
      { headers: { "X-Admin-Key": params.adminKey } }
    ),

  // 节点数据统一从云端读取
  adminAgents: (params: { limit?: number; adminKey: string }) =>
    cloudMembershipApi.get("/admin/agents", {
      params: params?.limit ? { limit: params.limit } : {},
      headers: { "X-Admin-Key": params.adminKey },
    }),


  adminTelemetryKeywords: (params: { agent_id?: string; limit?: number; adminKey: string }) =>
    cloudMembershipApi.get("/admin/telemetry/keywords", {
      params: {
        ...(params?.agent_id ? { agent_id: params.agent_id } : {}),
        ...(params?.limit ? { limit: params.limit } : {}),
      },
      headers: { "X-Admin-Key": params.adminKey },
    }),

  adminTelemetryKeywordDetail: (params: { report_id: number; limit?: number; adminKey: string }) =>
    cloudMembershipApi.get(`/admin/telemetry/keywords/${params.report_id}`, {
      params: params?.limit ? { limit: params.limit } : {},
      headers: { "X-Admin-Key": params.adminKey },
      }),
    

    adminDeleteTelemetryKeywords: (params: { report_ids: number[]; adminKey: string }) =>
      cloudMembershipApi.post(
        "/admin/telemetry/keywords/batch/delete",
        { report_ids: params.report_ids || [] },
        { headers: { "X-Admin-Key": params.adminKey } }
      ),

    adminSetAgentPolicy: (params: { agent_id: string; policy: Record<string, any>; adminKey: string }) =>
      cloudMembershipApi.post(
        "/admin/agents/policy",
        { agent_id: params.agent_id, policy: params.policy || {} },
        { headers: { "X-Admin-Key": params.adminKey } }
      ),

    agentGetPolicy: (params: { agent_id: string; adminKey: string }) =>
      cloudMembershipApi.get("/agent/policy", { params: { agent_id: params.agent_id }, headers: { "X-Admin-Key": params.adminKey } }),
      

  resolveAgentPolicy: async (params: { agent_id: string; adminKey: string }) => {
    const res = await cloudMembershipApi.get("/agent/policy", { params: { agent_id: params.agent_id }, headers: { "X-Admin-Key": params.adminKey } });
    return (res?.data || res)?.policy || {};
  },
};

const LOCAL_SESSION_SYNC_TIMEOUT_MS = 5000;
const SESSION_SYNCED_AT_KEY = "membership_session_synced_at";
const SESSION_SYNC_TTL_MS = 5 * 60 * 1000;

function markSessionSynced() {
  try {
    sessionStorage.setItem(SESSION_SYNCED_AT_KEY, String(Date.now()));
  } catch {
    // ignore
  }
}

function wasSessionSyncedRecently(): boolean {
  try {
    const ts = Number(sessionStorage.getItem(SESSION_SYNCED_AT_KEY) || 0);
    return ts > 0 && Date.now() - ts < SESSION_SYNC_TTL_MS;
  } catch {
    return false;
  }
}

/** 后台同步会话/配置，不阻塞进系统 */
export function prepareAppSessionInBackground(): void {
  void prepareAppSessionAfterLogin({ background: true }).catch(() => undefined);
}

/** 云端登录后同步本地会话（有超时，不阻塞进系统过久） */
export async function prepareAppSessionAfterLogin(opts?: {
  background?: boolean;
  skipCloudPull?: boolean;
}): Promise<boolean> {
  const background = !!opts?.background;
  try {
    const adminLogged =
      (typeof localStorage !== "undefined" &&
        localStorage.getItem("admin_console_logged_in") === "1") ||
      false;
    if (adminLogged && !getMembershipToken()) {
      const key =
        localStorage.getItem("membership_admin_key") ||
        localStorage.getItem("control_admin_key") ||
        "";
      if (key) {
        if (isDesktopClient()) {
          await waitLocalBackendReady(background ? 12000 : 20000);
        }
        const sync = await membershipApi.syncAdminSession();
        const payload = (sync as { data?: { token?: string } })?.data ?? sync;
        const t = String((payload as { token?: string })?.token || "").trim();
        if (t) setMembershipToken(t);
      }
    }
  } catch {
    // ignore
  }
  if (!getMembershipToken()) return false;
  if (isDesktopClient()) {
    await waitLocalBackendReady(background ? 12000 : 20000);
  }
  const isAdmin = isAdminConsoleSession();
  let syncOk = true;
  if (!isAdmin && !wasSessionSyncedRecently()) {
    syncOk = await Promise.race([
      membershipApi.syncLocalSession().then(() => true).catch(() => false),
      sleep(LOCAL_SESSION_SYNC_TIMEOUT_MS).then(() => false),
    ]);
    if (syncOk) markSessionSynced();
  }
  void configApi.prime(false);
  if (!opts?.skipCloudPull && isDesktopClient() && getMembershipToken()) {
    // 桌面端会员：登录后必须完成总部配置同步，AI 功能依赖本机后端持有的 Key
    const pullPromise = pullCloudAdminRuntimeCoordinated({ force: !background }).catch(() => null);
    if (background && isAdmin) {
      void pullPromise;
    } else {
      await Promise.race([pullPromise, sleep(background ? 5000 : 15000)]);
      if (!isAdmin) {
        try {
          await configApi.ensureRuntimeSecrets();
        } catch {
          // 启动任务时会再次 ensure 并给出明确提示
        }
      }
    }
  }
  return syncOk;
}

/** AI 分析/生图启动前：确保本机后端已从总部同步 Key（会员不接触明文 Key） */
export async function ensureRuntimeSecretsForAiTask(): Promise<void> {
  if (!isDesktopClient() || !getMembershipToken()) return;
  try {
    const res: any = await configApi.ensureRuntimeSecrets();
    const payload = res?.data ?? res;
    const data = payload?.data ?? payload ?? {};
    if (!data?.secrets_ready) {
      throw new Error(String(data?.message || "API 配置未就绪，请重新登录或联系管理员"));
    }
  } catch (e: any) {
    const msg =
      e?.response?.data?.detail ||
      e?.response?.data?.data?.message ||
      e?.message ||
      "API 配置未就绪，请重新登录或联系管理员";
    throw new Error(String(msg));
  }
}

export const taskApi = {
  /** 获取所有任务 */
  list: () => api.get("/tasks/list"),

  /** 获取任务详情 */
  get: (taskId: string) => api.get(`/tasks/${taskId}`),

  /** 停止任务 */
  stop: (taskId: string) => api.post(`/tasks/${taskId}/stop`),

  /** 暂停任务 */
  pause: (taskId: string) => api.post(`/tasks/${taskId}/pause`),

  /** 恢复任务 */
  resume: (taskId: string) => api.post(`/tasks/${taskId}/resume`),

  /** 删除任务 */
  remove: (taskId: string) => api.delete(`/tasks/${taskId}`),
};

// ===================== WebSocket 连接 =====================

export function createLogSocket(onMessage: (data: any) => void): WebSocket | null {
  try {
    const wsBase = getBackendHttpBase()
      ? getBackendHttpBase().replace(/^http:/, "ws:").replace(/^https:/, "wss:")
      : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;
    const token = getMembershipToken();
    const adminKey =
      (typeof localStorage !== "undefined" &&
        (localStorage.getItem("membership_admin_key") ||
          localStorage.getItem("control_admin_key") ||
          "")) ||
      "";
    const params = new URLSearchParams();
    if (token) params.set("token", token);
    if (adminKey) params.set("admin_key", adminKey);
    const qs = params.toString();
    const url = `${wsBase}/api/ws/logs${qs ? `?${qs}` : ""}`;
    const ws = new WebSocket(url);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (e) {
        console.error("WebSocket parse error:", e);
      }
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
    };

    return ws;
  } catch (e) {
    console.error("WebSocket connection failed:", e);
    return null;
  }
}

export function createTaskSocket(onMessage: (data: any) => void): WebSocket | null {
  try {
    const wsBase = getBackendHttpBase()
      ? getBackendHttpBase().replace(/^http:/, "ws:").replace(/^https:/, "wss:")
      : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;
    const ws = new WebSocket(`${wsBase}/api/ws/tasks`);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (e) {
        console.error("WebSocket parse error:", e);
      }
    };

    return ws;
  } catch (e) {
    console.error("WebSocket connection failed:", e);
    return null;
  }
}

export default api;
