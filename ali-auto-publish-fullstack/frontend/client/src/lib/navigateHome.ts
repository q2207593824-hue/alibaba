/** 进入系统首页（hash 路由：#/） */
export function navigateToHome(setLocation: (path: string) => void) {
  if (typeof window !== "undefined") {
    const targetHash = "#/";
    const current = window.location.hash || "";
    if (current !== targetHash && current !== "#") {
      window.location.hash = "/";
    }
  }
  setLocation("/");
}
