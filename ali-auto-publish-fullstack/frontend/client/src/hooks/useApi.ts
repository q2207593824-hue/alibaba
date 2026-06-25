/**
 * API Hooks - 封装常用的数据获取和任务管理逻辑
 *
 * 【如何修改】
 * - 添加新的 Hook → 在此文件中添加新的 useXxx 函数
 * - 修改轮询间隔 → 修改 POLL_INTERVAL 常量
 */
import { useState, useEffect, useCallback, useRef } from "react";

const POLL_INTERVAL = 2000; // 任务状态轮询间隔 (ms)

/** 通用数据获取 Hook */
export function useFetch<T>(fetcher: () => Promise<any>, deps: any[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await fetcher();
      setData(result?.data ?? result);
    } catch (e: any) {
      setError(e.message || "请求失败");
    } finally {
      setLoading(false);
    }
  }, deps);

  useEffect(() => {
    load();
  }, [load]);

  return { data, loading, error, reload: load };
}

/** 任务状态轮询 Hook */
export function useTaskStatus(
  statusFetcher: () => Promise<any>,
  enabled: boolean = true
) {
  const [status, setStatus] = useState<any>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!enabled) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }

    const poll = async () => {
      try {
        const result = await statusFetcher();
        setStatus(result?.data ?? result);
      } catch {
        // ignore polling errors
      }
    };

    poll(); // 立即执行一次
    intervalRef.current = setInterval(poll, POLL_INTERVAL);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [enabled]);

  return status;
}

/** WebSocket 日志 Hook */
export function useLogStream() {
  const [logs, setLogs] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    try {
      const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsHost = window.location.host;
      const ws = new WebSocket(`${wsProtocol}//${wsHost}/api/ws/logs`);

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === "log" && msg.data) {
            const entry = msg.data;
            const line = `[${entry.timestamp || ""}] [${entry.level || "INFO"}] ${entry.message || ""}`;
            setLogs((prev) => [...prev.slice(-500), line]); // 保留最近500条
          }
        } catch {
          // ignore parse errors
        }
      };

      wsRef.current = ws;
    } catch {
      // WebSocket not available
    }

    return () => {
      wsRef.current?.close();
    };
  }, []);

  const clearLogs = useCallback(() => setLogs([]), []);

  return { logs, clearLogs };
}
