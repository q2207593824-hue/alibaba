/**
 * ImageManager - 图片命名规范化管理页面
 * 对接后端: /api/images/*
 * 功能: 图片分组、场景匹配、主图补齐、文件重命名
 *
 * 【如何修改】
 * - 修改场景类型 → 修改 sceneTypes 数组
 * - 修改命名规则 → 修改 namingRules 数组
 * - 修改图片列表展示 → 修改 Image Table 部分
 */
import { useState, useEffect, useCallback, useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { imageApi, createLogSocket } from "@/lib/api";
import {
  FolderOpen,
  Play,
  CheckCircle2,
  FileImage,
  Tag,
  ChevronRight,
  RefreshCw,
  Grid3X3,
  List,
  Wand2,
} from "lucide-react";

const sceneTypes = [
  { id: "main", label: "主图", color: "bg-blue-100 text-blue-700" },
  { id: "detail", label: "详情图", color: "bg-emerald-100 text-emerald-700" },
  { id: "sku", label: "SKU图", color: "bg-amber-100 text-amber-700" },
  { id: "scene", label: "场景图", color: "bg-violet-100 text-violet-700" },
  { id: "white", label: "白底图", color: "bg-gray-100 text-gray-700" },
  { id: "size", label: "尺寸图", color: "bg-rose-100 text-rose-700" },
];

const namingRules = [
  {
    rule: "首图命名（position=1）",
    pattern: "{自由名}-1(-房子类型).jpg",
    example: "A-1-玻璃幕墙.jpg",
  },
  {
    rule: "主图2命名（position=2，可带价格）",
    pattern: "{自由名}-2(-价格).jpg",
    example: "A-2-4900.jpg",
  },
  {
    rule: "主图3~6命名（position=3~6）",
    pattern: "{自由名}-3.jpg / {自由名}-4.jpg / {自由名}-5.jpg / {自由名}-6.jpg",
    example: "A-3.jpg",
  },
  {
    rule: "SKU 图命名",
    pattern: "{自由名}-SKU-{规格}.jpg",
    example: "A-SKU-红色.jpg / A-SKU-Rose-Gold.jpg",
  },
  {
    rule: "自由名说明",
    pattern: "自由名 = 第一个 '-数字(1~6)' 或 '-SKU-' 之前的部分",
    example: "侧面玻璃幕墙-3.jpg → 自由名=侧面玻璃幕墙",
  },
];

export default function ImageManager() {
  const [groups, setGroups] = useState<any[]>([]);
  const [selectedGroup, setSelectedGroup] = useState(0);
  const [viewMode, setViewMode] = useState<"grid" | "list">("list");
  const [loading, setLoading] = useState(true);
  const [normalizing, setNormalizing] = useState(false);
  const [normConfig, setNormConfig] = useState<any>({});
  const [groupsText, setGroupsText] = useState("");
  const [mainLibText, setMainLibText] = useState("");
  const [savingConfig, setSavingConfig] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [logLoading, setLogLoading] = useState(false);
  const [previewUrlMap, setPreviewUrlMap] = useState<Record<string, string>>({});

  const safeJsonStringify = (value: unknown) => {
    try {
      return JSON.stringify(value ?? {}, null, 2);
    } catch {
      return "{}";
    }
  };

  const loadGroups = useCallback(async () => {
    try {
      setLoading(true);
      const result = await imageApi.getGroups();
      const data = result?.data || result;
      if (Array.isArray(data) && data.length > 0) {
        setGroups(data);
      }
    } catch {
      // 使用空数据，等后端就绪后自动加载
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadGroups();
    loadConfig();
  }, [loadGroups]);

  const loadConfig = async () => {
    try {
      const result = await imageApi.getConfig();
      const data = result?.data || result;
      setNormConfig(data || {});
      setGroupsText((data?.groups || []).join("\n"));
      setMainLibText(_formatMainLibText(data?.main_image_lib || {}));
    } catch (e: any) {
      toast.error(e.message || "加载配置失败");
    }
  };

  const saveConfig = async () => {
    try {
      setSavingConfig(true);
      await imageApi.updateConfig(normConfig);
      toast.success("配置已保存");
    } catch (e: any) {
      toast.error(e.message || "保存失败");
    } finally {
      setSavingConfig(false);
    }
  };

  const _formatMainLibText = (lib: Record<string, string>) => {
    const lines: string[] = [];
    for (let pos = 2; pos <= 6; pos++) {
      const value = lib?.[String(pos)] || lib?.[pos as any];
      if (value) lines.push(value);
    }
    return lines.join("\n");
  };

  const _parseMainLibText = (text: string) => {
    const map: Record<string, string> = {};
    const lines = text
      .split("\n")
      .map((v) => v.trim())
      .filter(Boolean);

    lines.forEach((line, idx) => {
      const pos = idx + 2;
      if (pos <= 6) {
        map[String(pos)] = line;
      }
    });
    return map;
  };

  const handleNormalize = async () => {
    try {
      const dirs = normConfig?.groups || [];
      if (!dirs.length) {
        toast.error("请先配置分组目录");
        return;
      }
      setLogLines([]);
      setLogLoading(true);
      setShowLog(true);
      setNormalizing(true);
      await imageApi.startNormalize({ source_dirs: dirs });
      toast.success("图片命名规范化任务已启动");
    } catch (e: any) {
      toast.error(e.message || "启动失败");
    } finally {
      setNormalizing(false);
      window.setTimeout(() => setLogLoading(false), 600);
    }
  };

  const fetchRecentLogs = useCallback(async () => {
    try {
      const res: any = await imageApi.getRecentLogs(500);
      const data = res?.data?.data || res?.data || res;
      const items = Array.isArray(data?.items) ? data.items : [];
      const next = items
        .map((it: any) => {
          const ts = it?.timestamp ? `${it.timestamp} ` : "";
          const lvl = it?.level ? `${it.level} ` : "";
          const mod = it?.module ? `${it.module} - ` : "";
          const msg = it?.message ?? "";
          const line = `${ts}${mod}${lvl}${msg}`.trim();
          return line;
        })
        .filter(Boolean);
      setLogLines(next.slice(-500));
      if (next.length) setLogLoading(false);
    } catch {
      // ignore: 轮询失败不影响主流程
    }
  }, []);

  useEffect(() => {
    const ws = createLogSocket((data) => {
      if (!data) return;
      const payload = data.data || data;
      const msg = payload.message || payload.msg || payload.text;
      if (!msg) return;
      setLogLoading(false);
      setLogLines((prev) => {
        const next = [...prev, String(msg)];
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

  useEffect(() => {
    if (!showLog) return;
    let cancelled = false;
    setLogLoading((v) => (logLines.length ? v : true));
    fetchRecentLogs();
    const timer = window.setInterval(() => {
      if (cancelled) return;
      fetchRecentLogs();
    }, 800);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showLog, fetchRecentLogs]);

  const currentGroup = groups[selectedGroup] || null;
  const currentImages = useMemo(
    () => (Array.isArray(currentGroup?.images) ? currentGroup.images : []),
    [currentGroup]
  );

  useEffect(() => {
    let cancelled = false;
    const urlsToRevoke: string[] = [];

    const loadPreviewUrls = async () => {
      if (!currentImages.length) {
        setPreviewUrlMap((prev) => (Object.keys(prev).length ? {} : prev));
        return;
      }

      const entries = await Promise.all(
        currentImages.map(async (img: any) => {
          const p = String(img?.path || "");
          if (!p) return [p, ""] as const;
          try {
            const res: any = await imageApi.getImageFileBlob(p);
            const blob = res instanceof Blob ? res : res?.data;
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
    };
  }, [currentImages]);

  const getSceneBadge = (scene: string) => {
    const s = sceneTypes.find((t) => t.id === scene);
    if (!s) return null;
    return <Badge variant="outline" className={`text-[10px] h-5 ${s.color} border-0`}>{s.label}</Badge>;
  };

  return (
    <div className="p-8">
      {/* Page Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>图片管理</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">图片规范化</span>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">图片命名规范化</h1>
            <p className="text-sm text-muted-foreground mt-1">自动分组、场景识别、命名规范化和主图补齐</p>
          </div>
          <div className="flex gap-3">
            <Button variant="outline" onClick={loadGroups} className="gap-2">
              <RefreshCw className="w-4 h-4" />
              刷新
            </Button>
            <Button variant="outline" onClick={saveConfig} disabled={savingConfig} className="gap-2">
              <Wand2 className="w-4 h-4" />
              {savingConfig ? "保存中..." : "保存配置"}
            </Button>
            <Button onClick={handleNormalize} disabled={normalizing} className="gap-2">
              <Play className="w-4 h-4" />
              {normalizing ? "执行中..." : "执行规范化"}
            </Button>
            <Button variant="outline" onClick={() => setShowLog(true)} className="gap-2">
              <List className="w-4 h-4" />
              查看日志
            </Button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-6">
        <Dialog open={showLog} onOpenChange={setShowLog}>
          <DialogContent className="w-[95vw] max-w-none max-h-[85vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>运行日志</DialogTitle>
            </DialogHeader>
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs text-muted-foreground">仅显示最近 500 行</div>
              <Button variant="outline" size="sm" onClick={() => setLogLines([])}>清空</Button>
            </div>
            <div className="bg-muted/30 rounded-lg p-3 font-mono text-xs whitespace-pre-wrap max-h-[55vh] overflow-y-auto min-h-[180px]">
              {logLoading ? "日志连接中..." : logLines.length === 0 ? "暂无日志" : logLines.join("\n")}
            </div>
          </DialogContent>
        </Dialog>
        {/* Left: Folder Tree */}
        <div className="col-span-3 space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm">规范化配置</CardTitle>
                <Dialog>
                  <DialogTrigger asChild>
                    <Button variant="outline" size="sm" className="gap-2">
                      <Wand2 className="w-4 h-4" />
                      编辑配置
                    </Button>
                  </DialogTrigger>
                  <DialogContent className="!w-[75vw] !max-w-none max-h-[85vh] overflow-y-auto">
                    <DialogHeader>
                      <DialogTitle>规范化配置</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-4 pb-4">
                      <div className="grid grid-cols-2 gap-4">
                        <div className="space-y-2">
                          <Label className="text-xs text-muted-foreground">分组目录（每行一个）</Label>
                          <Textarea
                            value={groupsText}
                            onChange={(e) => {
                              const text = e.target.value;
                              setGroupsText(text);
                              setNormConfig((prev: any) => ({
                                ...prev,
                                groups: text
                                  .split("\n")
                                  .map((v) => v.trim())
                                  .filter(Boolean),
                              }));
                            }}
                            className="text-xs font-mono min-h-[180px]"
                            placeholder="D:\\素材\\组1\nD:\\素材\\组2"
                          />
                          <div className="text-[10px] text-muted-foreground">提示：这里填原始素材分组目录，不是输出目录。</div>
                        </div>

                        <div className="space-y-2">
                          <Label className="text-xs text-muted-foreground">主图库路径（每行一个，对应主图2~6）</Label>
                          <Textarea
                            value={mainLibText}
                            onChange={(e) => {
                              const text = e.target.value;
                              setMainLibText(text);
                              const map = _parseMainLibText(text);
                              setNormConfig((prev: any) => ({ ...prev, main_image_lib: map }));
                            }}
                            className="text-xs font-mono min-h-[180px]"
                            placeholder="D:\\主图\\主图2\nD:\\主图\\主图3\nD:\\主图\\主图4\nD:\\主图\\主图5\nD:\\主图\\主图6"
                          />
                          <div className="text-[10px] text-muted-foreground">第1行=主图2，第2行=主图3 … 第5行=主图6。</div>
                        </div>
                      </div>

                      <div className="grid grid-cols-1 gap-4">
                        <div className="grid grid-cols-2 gap-3">
                          <div className="space-y-2">
                            <Label className="text-xs text-muted-foreground">白名单（JSON）</Label>
                            <Textarea
                              value={safeJsonStringify(normConfig?.house_type_allowed_scenes || {})}
                              onChange={(e) => {
                                try {
                                  const v = JSON.parse(e.target.value || "{}");
                                  setNormConfig((prev: any) => ({ ...prev, house_type_allowed_scenes: v }));
                                } catch {
                                  // ignore invalid json
                                }
                              }}
                              className="text-xs font-mono min-h-[160px]"
                            />
                          </div>

                          <div className="space-y-2">
                            <Label className="text-xs text-muted-foreground">黑名单（JSON）</Label>
                            <Textarea
                              value={safeJsonStringify(normConfig?.house_type_forbidden_scenes || {})}
                              onChange={(e) => {
                                try {
                                  const v = JSON.parse(e.target.value || "{}");
                                  setNormConfig((prev: any) => ({ ...prev, house_type_forbidden_scenes: v }));
                                } catch {
                                  // ignore invalid json
                                }
                              }}
                              className="text-xs font-mono min-h-[160px]"
                            />
                          </div>
                        </div>

                        <div className="grid grid-cols-2 gap-3">
                          <div className="space-y-2">
                            <Label className="text-xs text-muted-foreground">首图名称映射文件</Label>
                            <Input
                              value={normConfig?.name_mapping_file || ""}
                              onChange={(e) =>
                                setNormConfig((prev: any) => ({ ...prev, name_mapping_file: e.target.value }))
                              }
                              className="text-xs font-mono"
                              placeholder="D:\\path\\图片名称映射.txt"
                            />
                          </div>

                          <div className="space-y-2">
                            <Label className="text-xs text-muted-foreground">已处理记录文件</Label>
                            <Input
                              value={normConfig?.processed_products_file || ""}
                              onChange={(e) =>
                                setNormConfig((prev: any) => ({ ...prev, processed_products_file: e.target.value }))
                              }
                              className="text-xs font-mono"
                              placeholder="D:\\path\\已处理产品记录.txt"
                            />
                          </div>
                        </div>

                      </div>

                      <div className="flex justify-end gap-2 pt-2">
                        <Button variant="outline" onClick={saveConfig} disabled={savingConfig}>
                          {savingConfig ? "保存中..." : "保存配置"}
                        </Button>
                      </div>
                    </div>
                  </DialogContent>
                </Dialog>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="text-xs text-muted-foreground">配置已移入弹窗编辑。</div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm">图片分组</CardTitle>
                <Badge variant="secondary" className="text-xs">{groups.length} 组</Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-1">
              {loading ? (
                <div className="text-xs text-muted-foreground py-4 text-center">加载中...</div>
              ) : groups.length === 0 ? (
                <div className="text-xs text-muted-foreground py-4 text-center">
                  暂无数据，请在配置中设置图片目录后刷新
                </div>
              ) : (
                groups.map((group: any, i: number) => (
                  <button
                    key={i}
                    onClick={() => setSelectedGroup(i)}
                    className={`w-full text-left px-3 py-2.5 rounded-lg text-sm transition-all ${
                      selectedGroup === i
                        ? "bg-primary/5 border border-primary/20 text-foreground"
                        : "hover:bg-accent/50 text-muted-foreground"
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <FolderOpen className={`w-4 h-4 shrink-0 ${selectedGroup === i ? "text-primary" : ""}`} />
                      <div className="overflow-hidden">
                        <div className="truncate font-medium text-xs">{group.name || group.folder}</div>
                        <div className="text-[10px] text-muted-foreground">{group.images?.length || 0} 张图片</div>
                      </div>
                    </div>
                  </button>
                ))
              )}
            </CardContent>
          </Card>

          {/* Scene Stats */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm">场景分类统计</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {sceneTypes.map((scene) => {
                  const count = currentImages.filter((img: any) => img.scene === scene.id).length;
                  return (
                    <div key={scene.id} className="flex items-center justify-between text-xs">
                      <Badge variant="outline" className={`${scene.color} border-0 text-[10px]`}>{scene.label}</Badge>
                      <span className="text-muted-foreground">{count} 张</span>
                    </div>
                  );
                })}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Right: Image List */}
        <div className="col-span-9 space-y-4">
          <Card>
            <CardContent className="py-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <h3 className="text-sm font-medium">{currentGroup?.name || "请选择分组"}</h3>
                  <Badge variant="secondary" className="text-xs">{currentImages.length} 张</Badge>
                </div>
                <div className="flex items-center gap-2">
                  <Button variant={viewMode === "list" ? "secondary" : "ghost"} size="sm" onClick={() => setViewMode("list")}>
                    <List className="w-4 h-4" />
                  </Button>
                  <Button variant={viewMode === "grid" ? "secondary" : "ghost"} size="sm" onClick={() => setViewMode("grid")}>
                    <Grid3X3 className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-0">
              {currentImages.length === 0 ? (
                <div className="py-12 text-center text-sm text-muted-foreground">暂无图片数据</div>
              ) : (
                <div className="max-h-[520px] overflow-auto rounded-lg">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 bg-muted/80 backdrop-blur z-10">
                      <tr className="border-b bg-muted/30">
                        <th className="text-left py-3 px-4 font-medium text-xs text-muted-foreground">图片</th>
                        <th className="text-left py-3 px-4 font-medium text-xs text-muted-foreground">文件名</th>
                        <th className="text-left py-3 px-4 font-medium text-xs text-muted-foreground">场景类型</th>
                        <th className="text-left py-3 px-4 font-medium text-xs text-muted-foreground">尺寸</th>
                        <th className="text-left py-3 px-4 font-medium text-xs text-muted-foreground">大小</th>
                        <th className="text-left py-3 px-4 font-medium text-xs text-muted-foreground">状态</th>
                      </tr>
                    </thead>
                    <tbody>
                      {currentImages.map((img: any, i: number) => (
                        <tr key={i} className="border-b last:border-0 hover:bg-accent/30 transition-colors">
                          <td className="py-3 px-4">
                            <div className="w-16 h-16 rounded border border-border/60 overflow-hidden bg-muted/20">
                              <img src={previewUrlMap[String(img.path || "")] || ""} alt={img.name} className="w-full h-full object-cover" loading="lazy" />
                            </div>
                          </td>
                          <td className="py-3 px-4">
                            <div className="flex items-center gap-2">
                              <FileImage className="w-4 h-4 text-muted-foreground shrink-0" />
                              <span className="font-mono text-xs">{img.name}</span>
                            </div>
                          </td>
                          <td className="py-3 px-4">{getSceneBadge(img.scene)}</td>
                          <td className="py-3 px-4 text-xs text-muted-foreground">{img.size || "--"}</td>
                          <td className="py-3 px-4 text-xs text-muted-foreground">{img.fileSize || "--"}</td>
                          <td className="py-3 px-4">
                            <Badge variant="outline" className={`text-[10px] h-5 ${img.normalized ? "bg-emerald-50 text-emerald-600 border-emerald-200" : "bg-amber-50 text-amber-700 border-amber-200"}`}>
                              <CheckCircle2 className="w-3 h-3 mr-1" />
                              {img.normalized ? "已规范" : "待处理"}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Naming Rules */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <Tag className="w-4 h-4" />
                命名规则
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-3 gap-3">
                {namingRules.map((rule) => (
                  <div key={rule.rule} className="p-3 bg-muted/30 rounded-lg">
                    <div className="text-xs font-medium mb-1">{rule.rule}</div>
                    <div className="text-[10px] text-muted-foreground font-mono">{rule.pattern}</div>
                    <div className="text-[10px] text-primary/70 font-mono mt-1">例: {rule.example}</div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
