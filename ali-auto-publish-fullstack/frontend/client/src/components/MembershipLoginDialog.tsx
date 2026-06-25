import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";
import {
  ensureDesktopBackendForLogin,
  membershipApi,
  notifyAuthChanged,
  prepareAppSessionAfterLogin,
  setMembershipToken,
} from "@/lib/api";
import { navigateToHome } from "@/lib/navigateHome";
import { useLocation } from "wouter";

const ADMIN_KEY_STORE = "membership_admin_key";
const CONTROL_ADMIN_KEY_STORE = "control_admin_key";
const STORE_PROFILE_CACHE_KEY = "membership_store_profile_cache";

export type MembershipLoginDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 弹窗标题下的说明 */
  description?: string;
  onSuccess?: () => void;
  /** 登录成功后直接进入系统首页（默认 true） */
  redirectToApp?: boolean;
};

export type UnifiedLoginData = {
  role?: "admin" | "member";
  token?: string;
  expire_at?: string;
  admin_user?: string;
  admin_key?: string;
};

async function applyAdminSession(uname: string, adminData: Record<string, unknown>): Promise<"admin"> {
  const key = String(adminData?.admin_key || "");
  if (!key) throw new Error("管理员登录失败：未返回 admin_key（请配置 ALI_ADMIN_API_KEY）");

  localStorage.setItem(ADMIN_KEY_STORE, key);
  localStorage.setItem(CONTROL_ADMIN_KEY_STORE, key);
  localStorage.setItem("admin_console_logged_in", "1");
  localStorage.setItem("admin_console_user", String(adminData?.admin_user || uname || "admin"));

  let token = String(adminData?.token || "").trim();
  if (!token) {
    try {
      const sync = await membershipApi.syncAdminSession();
      const payload = (sync as any)?.data ?? sync;
      token = String(payload?.token || "").trim();
    } catch {
      // 下面再试
    }
  }
  if (!token) {
    throw new Error("管理员会话未建立，请确认本机 backend 已启动并重试登录");
  }
  setMembershipToken(token);
  notifyAuthChanged();
  return "admin";
}

async function applyMemberSession(data: UnifiedLoginData): Promise<"member"> {
  const t = String(data?.token || "").trim();
  if (!t) throw new Error("会员登录成功但未返回 token");

  try {
    localStorage.removeItem(STORE_PROFILE_CACHE_KEY);
  } catch {
    // ignore
  }
  setMembershipToken(t);
  localStorage.removeItem("admin_console_logged_in");
  localStorage.removeItem(ADMIN_KEY_STORE);
  localStorage.removeItem(CONTROL_ADMIN_KEY_STORE);
  // syncLocalSession 由 prepareAppSessionAfterLogin 统一执行，避免登录链重复等待
  return "member";
}

async function handleUnifiedLoginData(data: UnifiedLoginData, uname: string): Promise<"admin" | "member"> {
  const role = String(data?.role || "").trim().toLowerCase();
  if (role === "admin") {
    return applyAdminSession(uname, data);
  }
  if (role === "member") {
    return applyMemberSession(data);
  }
  throw new Error("登录响应异常：未返回 role");
}

/** 统一登录：后端根据 admin_accounts / users 自动识别管理员或会员 */
export async function performMembershipLogin(username: string, password: string): Promise<"admin" | "member"> {
  const uname = String(username || "").trim();
  const pwd = String(password || "").trim();
  if (!uname || !pwd) {
    throw new Error("请输入账号和密码");
  }

  const data = await membershipApi.loginUnified({ username: uname, password: pwd });
  return handleUnifiedLoginData(data, uname);
}

export default function MembershipLoginDialog({
  open,
  onOpenChange,
  description = "登录后自动识别管理员或会员账号，无需手动选择。",
  onSuccess,
  redirectToApp = true,
}: MembershipLoginDialogProps) {
  const [, setLocation] = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setPassword("");
  }, [open]);

  const submit = async () => {
    if (loading) return;
    setLoading(true);
    try {
      if ((window as any)?.desktopEnv?.isElectron) {
        toast.info("正在启动本地服务，请稍候…", { duration: 4000 });
        await ensureDesktopBackendForLogin(30000);
      }
      const kind = await performMembershipLogin(username, password);
      toast.success(kind === "admin" ? "管理员登录成功" : "会员登录成功，正在进入系统…");
      onOpenChange(false);
      onSuccess?.();
      if (redirectToApp) {
        navigateToHome(setLocation);
        void prepareAppSessionAfterLogin({ background: kind === "admin" }).then((synced) => {
          if (!synced && kind === "member") {
            toast.warning("本地服务仍在启动，部分功能可能稍后再试");
          }
        });
      }
    } catch (e: any) {
      toast.error(e?.message || "登录失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>登录</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>账号</Label>
            <Input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="管理员或会员账号"
              autoComplete="username"
              disabled={loading}
            />
          </div>
          <div className="space-y-1.5">
            <Label>密码</Label>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="密码"
              autoComplete="current-password"
              disabled={loading}
              onKeyDown={(e) => {
                if (e.key === "Enter") void submit();
              }}
            />
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
              取消
            </Button>
            <Button onClick={() => void submit()} disabled={loading}>
              {loading ? "登录中..." : "登录"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
