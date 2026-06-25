import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";
import { defineConfig } from "vite";

function resolveDevBackendPort(): string {
  const fromEnv = process.env.VITE_DEV_BACKEND_PORT || process.env.BACKEND_PORT;
  if (fromEnv) return fromEnv;
  try {
    const portFile = path.resolve(import.meta.dirname, ".dev-backend-port");
    if (fs.existsSync(portFile)) {
      const port = fs.readFileSync(portFile, "utf-8").trim();
      if (port) return port;
    }
  } catch {
    // ignore
  }
  return "8000";
}

const devBackendPort = resolveDevBackendPort();
const devBackendTarget = `http://127.0.0.1:${devBackendPort}`;
console.log(`[vite] API proxy → ${devBackendTarget}`);

/**
 * Vite 配置
 * - 移除了 Manus 平台依赖 (vite-plugin-manus-runtime, debug-collector)
 * - 添加了 API 代理指向 FastAPI 后端 (默认 localhost:8000)
 *
 * 【如何修改】
 * - 修改后端端口 → 修改 proxy 中的 target
 * - 修改前端端口 → 修改 server.port
 * - 添加新的路径别名 → 修改 resolve.alias
 */
export default defineConfig({
  // Electron 打包后通过 file:// 加载前端时需要相对资源路径，避免白屏
  base: "./",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "client", "src"),
      "@shared": path.resolve(import.meta.dirname, "shared"),
    },
  },
  envDir: path.resolve(import.meta.dirname),
  root: path.resolve(import.meta.dirname, "client"),
  build: {
    outDir: path.resolve(import.meta.dirname, "dist"),
    emptyOutDir: true,
  },
  server: {
    port: 3000,
    strictPort: false,
    host: true,
    proxy: {
      // 业务 API → 本地 FastAPI
      "/api": {
        target: devBackendTarget,
        changeOrigin: true,
        ws: true,
      },
      // 会员/积分 API → 云端（避免浏览器直连跨域；路径 /cloud-api/* → https://echo-yiwu.cloud/api/*）
      "/cloud-api": {
        target: process.env.VITE_CLOUD_PROXY_TARGET || "https://echo-yiwu.cloud",
        changeOrigin: true,
        secure: true,
        rewrite: (path) => path.replace(/^\/cloud-api/, "/api"),
      },
    },
    allowedHosts: true,
    fs: {
      strict: true,
      deny: ["**/.*"],
    },
  },
});
