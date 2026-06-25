export {};

declare global {
  interface Window {
    desktopEnv?: {
      isElectron?: boolean;
      waitBackendReady?: (timeoutMs?: number) => Promise<boolean>;
      restartBackend?: () => Promise<boolean>;
      getRuntimeInfo?: () => Promise<{
        appVersion: string;
        backendPort: string;
        isPackaged: boolean;
        logPath: string;
        recentLogs: string[];
      }>;
      exportRuntimeLog?: () => Promise<{ ok: boolean; canceled?: boolean; filePath?: string; error?: string }>;
    };
  }
}
