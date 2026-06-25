import { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { ChevronRight, Play, Pause, RefreshCw, Search } from "lucide-react";
import { toast } from "sonner";
import { configApi, createLogSocket, dataApi } from "@/lib/api";

export default function StoreImageCollect() {
  const [isRunning, setIsRunning] = useState(false);
  const [logs, setLogs] = useState<string[]>(["[系统] 店铺图片采集模块已就绪"]);

  const [targetUrl, setTargetUrl] = useState("");
  const [saveDir, setSaveDir] = useState("");
  const [maxPages, setMaxPages] = useState<number>(100);

  const [keyword, setKeyword] = useState("");
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [titles, setTitles] = useState<any[]>([]);
  const [titleTotal, setTitleTotal] = useState(0);
  const [previewUrlMap, setPreviewUrlMap] = useState<Record<string, string>>({});

  const taskType = "store_image_collect";
  const lastStatusRef = useRef<string>("idle");

  const loadConfig = async () => {
    try {
      const dd = (await configApi.getSection("data_download")) || {};
      setTargetUrl(dd?.store_image_target_url || "https://szdabojin.en.alibaba.com/productlist.html");
      setSaveDir(dd?.store_image_save_dir || "");
      setMaxPages(Number(dd?.store_image_max_pages || 100));
    } catch (e: any) {
      toast.error(e.message || "加载配置失败");
    }
  };

  const saveConfig = async () => {
    try {
      const current = (await configApi.getSection("data_download")) || {};
      await configApi.updateSection("data_download", {
        ...current,
        store_image_target_url: targetUrl,
        store_image_save_dir: saveDir,
        store_image_max_pages: Math.max(1, Number(maxPages || 1)),
      });
      toast.success("店铺图片采集配置已保存");
      refreshImages();
    } catch (e: any) {
      toast.error(e.message || "保存失败");
    }
  };

  const refreshStatus = async () => {
    try {
      const res = await dataApi.getDownloadStatus(taskType);
      const payload = res?.data || res;
      const s = payload?.data || payload;
      const status = String(s?.status || "idle");

      setIsRunning(status === "running" || status === "stopping");

      if (status !== lastStatusRef.current) {
        if (status === "running") {
          setLogs((prev) => [...prev, "[系统] 店铺图片采集任务运行中..."]);
        } else if (status === "completed") {
          const msg = String(s?.current_step || "任务已完成");
          setLogs((prev) => [...prev, `[完成] ${msg}`]);
          toast.success("店铺图片采集已完成");
          refreshImages();
        } else if (status === "failed") {
          const err = String(s?.error || "未知错误");
          const step = String(s?.current_step || "");
          setLogs((prev) => [...prev, `[失败] ${step || "任务执行失败"} | ${err}`]);
          toast.error(`采集失败: ${err}`);
        } else if (status === "stopping") {
          setLogs((prev) => [...prev, "[系统] 正在停止任务..."]);
        }
        lastStatusRef.current = status;
      }
    } catch {
      // ignore
    }
  };

  const refreshImages = async () => {
    try {
      const res = await dataApi.getStoreImageList(saveDir || undefined, keyword || undefined);
      const payload = res?.data || res;
      const data = payload?.data || payload;
      setItems(Array.isArray(data?.items) ? data.items : []);
      setTotal(Number(data?.total || 0));
      setTitles(Array.isArray(data?.titles) ? data.titles : []);
      setTitleTotal(Number(data?.title_total || 0));
    } catch {
      setItems([]);
      setTotal(0);
      setTitles([]);
      setTitleTotal(0);
    }
  };

  const handleStart = async () => {
    try {
      if (!saveDir) {
        toast.error("请先配置保存目录");
        return;
      }
      if (!targetUrl) {
        toast.error("请先配置目标店铺产品列表页");
        return;
      }

      // 启动前先保存当前配置，避免后端读取旧配置导致“启动即退出”
      const current = (await configApi.getSection("data_download")) || {};
      await configApi.updateSection("data_download", {
        ...current,
        store_image_target_url: targetUrl,
        store_image_save_dir: saveDir,
        store_image_max_pages: Math.max(1, Number(maxPages || 1)),
      });

      setIsRunning(true);
      setLogs((prev) => [...prev, "[系统] 已提交任务，正在等待后端执行..."]);
      await dataApi.startDownload({ task_type: taskType });
      toast.success("店铺图片采集已启动");
      refreshStatus();
    } catch (e: any) {
      toast.error(e.message || "启动失败");
      setIsRunning(false);
    }
  };

  const handleStop = async () => {
    try {
      await dataApi.stopDownload(taskType);
      toast.info("已停止");
      refreshStatus();
      setIsRunning(false);
    } catch (e: any) {
      toast.error(e.message || "停止失败");
    }
  };

  useEffect(() => {
    loadConfig();
  }, []);

  useEffect(() => {
    void refreshStatus();
  }, []);

  useEffect(() => {
    if (!isRunning) return;
    const timer = setInterval(refreshStatus, 3000);
    return () => clearInterval(timer);
  }, [isRunning]);

  useEffect(() => {
    if (!saveDir) return;
    const timer = setTimeout(() => {
      refreshImages();
    }, 250);
    return () => clearTimeout(timer);
  }, [saveDir, keyword]);

  useEffect(() => {
    const ws = createLogSocket((data) => {
      if (!data) return;
      const payload = data.data || data;
      const moduleName = String(payload?.module || "");
      const msg = payload.message || payload.msg || payload.text;
      if (!msg) return;
      if (moduleName && moduleName !== "data_download") return;
      const text = String(msg);
      if (!text.includes("图片")) return;
      setLogs((prev) => {
        const next = [...prev, text];
        return next.slice(-500);
      });
    });

    return () => {
      try {
        ws?.close();
      } catch {
        // ignore
      }
    };
  }, []);

  const preview = useMemo(() => items.slice(0, 120), [items]);

  useEffect(() => {
    let cancelled = false;
    const urlsToRevoke: string[] = [];

    const loadPreviewUrls = async () => {
      if (preview.length === 0) {
        setPreviewUrlMap({});
        return;
      }

      const entries = await Promise.all(
        preview.map(async (it: any) => {
          const p = String(it?.path || "");
          if (!p) return [p, ""] as const;
          try {
            const res = await dataApi.getStoreImageFileBlob(p);
            const blob = res instanceof Blob ? res : (res as any)?.data;
            if (!(blob instanceof Blob)) return [p, ""] as const;
            const url = URL.createObjectURL(blob);
            urlsToRevoke.push(url);
            return [p, url] as const;
          } catch {
            return [p, ""] as const;
          }
        })
      );

      if (cancelled) {
        urlsToRevoke.forEach((u) => URL.revokeObjectURL(u));
        return;
      }

      const next: Record<string, string> = {};
      for (const [k, v] of entries) {
        if (k && v) next[k] = v;
      }
      setPreviewUrlMap(next);
    };

    loadPreviewUrls();

    return () => {
      cancelled = true;
      urlsToRevoke.forEach((u) => URL.revokeObjectURL(u));
      setPreviewUrlMap({});
    };
  }, [preview]);

  return (
    <div className="p-8">
      <div className="mb-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>图片管理</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">店铺图片采集</span>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">店铺图片采集</h1>
            <p className="text-sm text-muted-foreground mt-1">按产品ID抓取店铺列表页图片并保存到本地目录</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={isRunning ? "default" : "secondary"}>{isRunning ? "运行中" : "待启动"}</Badge>
            <Button onClick={isRunning ? handleStop : handleStart} variant={isRunning ? "destructive" : "default"} className="gap-2">
              {isRunning ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
              {isRunning ? "停止" : "运行"}
            </Button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2 space-y-4">
          <Card>
            <CardHeader className="pb-3"><CardTitle className="text-sm">标题模块</CardTitle></CardHeader>
            <CardContent>
              <div className="h-64 overflow-auto rounded-lg border border-border/60">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-muted/70">
                    <tr className="border-b">
                      <th className="text-left py-2 px-3">产品ID</th>
                      <th className="text-left py-2 px-3">产品标题</th>
                    </tr>
                  </thead>
                  <tbody>
                    {titles.length === 0 ? (
                      <tr><td colSpan={2} className="py-6 text-center text-muted-foreground">暂无标题</td></tr>
                    ) : titles.slice(0, 300).map((t: any, idx: number) => (
                      <tr key={`${t.id}-${idx}`} className="border-b last:border-0">
                        <td className="py-2 px-3 font-mono">{t.id}</td>
                        <td className="py-2 px-3">{t.title}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">图片模块</CardTitle>
                <div className="text-xs text-muted-foreground">图片 {total} 张 · 标题 {titleTotal} 条（最多预览120张）</div>
              </div>
            </CardHeader>
            <CardContent>
              {preview.length === 0 ? (
                <div className="h-64 rounded-lg border border-border/50 flex items-center justify-center text-xs text-muted-foreground">暂无图片</div>
              ) : (
                <div className="grid grid-cols-4 gap-3 max-h-[620px] overflow-auto">
                  {preview.map((it: any) => (
                    <div key={it.path} className="rounded-lg border border-border/60 p-2">
                      <div className="aspect-square bg-muted/40 rounded-md overflow-hidden">
                        <img src={previewUrlMap[String(it.path || "")] || ""} alt={it.name} className="w-full h-full object-cover" loading="lazy" />
                      </div>
                      <div className="mt-2 text-[11px] font-mono truncate" title={it.name}>{it.name}</div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3"><CardTitle className="text-sm">搜索模块</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              <Label className="text-xs text-muted-foreground">按文件名/产品ID搜索</Label>
              <div className="flex items-center gap-2">
                <Input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="输入关键词" className="text-xs" />
                <Button size="sm" onClick={refreshImages} className="gap-1.5"><Search className="w-3.5 h-3.5" />搜索</Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3"><CardTitle className="text-sm">配置模块</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">目标店铺产品列表页</Label>
                <Input value={targetUrl} onChange={(e) => setTargetUrl(e.target.value)} className="text-xs font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">保存图片目录</Label>
                <Input value={saveDir} onChange={(e) => setSaveDir(e.target.value)} className="text-xs font-mono" />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">最大页数</Label>
                <Input type="number" value={maxPages} onChange={(e) => setMaxPages(Number(e.target.value || 1))} className="text-xs font-mono" />
              </div>
              <Separator />
              <div className="flex items-center gap-2">
                <Button size="sm" variant="outline" onClick={saveConfig}>保存配置</Button>
                <Button size="sm" variant="ghost" onClick={loadConfig}>重载</Button>
                <Button size="sm" variant="ghost" onClick={refreshImages} className="gap-1.5"><RefreshCw className="w-3.5 h-3.5" />刷新图片</Button>
              </div>
            </CardContent>
          </Card>


          <Card>
            <CardHeader className="pb-3"><CardTitle className="text-sm">运行日志</CardTitle></CardHeader>
            <CardContent>
              <div className="h-56 overflow-y-auto rounded-lg bg-gray-950 p-4">
                <div className="space-y-1 font-mono text-xs">
                  {logs.map((log, i) => <div key={i} className="text-gray-300">{log}</div>)}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
