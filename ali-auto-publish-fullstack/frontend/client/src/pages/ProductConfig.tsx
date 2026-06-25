/**
 * ProductConfig - 配置管理页面
 * 对接后端: /api/config
 * 功能: 管理发品配置、属性映射、价格模板、Cookie管理
 *
 * 【如何修改】
 * - 增加新的配置 Tab → 在 Tabs 组件中添加新的 TabsTrigger + TabsContent
 * - 修改属性映射表 → 修改 "attrs" TabsContent 部分
 * - 修改价格模板 → 修改 "price" TabsContent 部分
 */
import { useState, useEffect, useMemo, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { configApi, subscribeConfigUpdates } from "@/lib/api";
import {
  DEFAULT_PRICE_UNIT,
  isValidPriceUnit,
  PriceUnitSelect,
} from "@/components/PriceUnitSelect";
import {
  Settings,
  Globe,
  DollarSign,
  Tag,
  Save,
  ChevronRight,
  Plus,
  Trash2,
  Copy,
  Key,
  FolderOpen,
  RefreshCw,
} from "lucide-react";

const verifySpecFieldsPersisted = (
  sent: Record<string, any>,
  saved: Record<string, any>,
) => {
  const sentGroups = sent?.attributes?.specifications_by_group || {};
  const savedGroups = saved?.attributes?.specifications_by_group || {};
  for (const [groupName, specs] of Object.entries(sentGroups)) {
    for (const [specName, item] of Object.entries((specs || {}) as Record<string, any>)) {
      const savedItem = savedGroups?.[groupName]?.[specName];
      if (item?.enable_spec_image && !savedItem?.enable_spec_image) {
        throw new Error(
          "规格图开关未写入成功：前端可能连到了旧版后端（8000 安装包）。请先运行 python run.py，再重启 pnpm run dev。",
        );
      }
      if (item?.enable_sale_attribute === true && savedItem?.enable_sale_attribute !== true) {
        throw new Error(
          "顶部规格项开关未写入成功：请确认后端为 python run.py（8001），并重启 pnpm run dev 后再保存。",
        );
      }
    }
  }
};

const extractCategoryIdFromUrl = (url: string) => {
  const m = String(url || "").match(/[?&]catId=(\d+)/i);
  return m ? m[1] : "";
};

const syncCategorySpecsForGroup = (
  cfg: Record<string, any>,
  groupName: string,
  groupSpecs: Record<string, any>,
) => {
  const url = cfg?.group_urls?.group_url_map?.[groupName] || "";
  const catId = extractCategoryIdFromUrl(url);
  if (!catId) return cfg;
  const byCat = { ...(cfg.attributes?.specifications_by_category_id || {}) };
  byCat[catId] = { ...groupSpecs };
  return {
    ...cfg,
    attributes: {
      ...(cfg.attributes || {}),
      specifications_by_category_id: byCat,
    },
  };
};

const syncAllCategorySpecs = (cfg: Record<string, any>) => {
  const groupMap = cfg?.group_urls?.group_url_map || {};
  const specsByGroup = cfg?.attributes?.specifications_by_group || {};
  const aliasMap = cfg?.attributes?.specification_group_alias || {};
  let next = cfg;
  Object.keys(groupMap).forEach((groupName) => {
    const sourceGroup = aliasMap[groupName] || groupName;
    const specs = specsByGroup[groupName] || specsByGroup[sourceGroup];
    if (specs) {
      next = syncCategorySpecsForGroup(next, groupName, specs);
    }
  });
  return next;
};

const inferLegacyEnableSaleAttribute = (spec: any, name: string) => {
  if (String(name || "").includes("_规格_p-")) return false;
  if (String(spec?.container_id || "").trim()) return true;
  if (spec?.enable_spec_image) return true;
  if ((spec?.values_pool || []).length > 0) return true;
  if ((spec?.default_values || []).length > 0) return true;
  return false;
};

const deriveSaleAttributeValue = (containerId: string, existing = "") => {
  const kept = String(existing || "").trim();
  if (kept) return kept;
  const cid = String(containerId || "").trim();
  if (cid.startsWith("p-")) return cid.slice(2);
  if (cid) return cid;
  return "";
};

const resolveEnableSaleAttribute = (spec: any, name: string) => {
  if (typeof spec?.enable_sale_attribute === "boolean") return spec.enable_sale_attribute;
  return inferLegacyEnableSaleAttribute(spec, name);
};

const DEFAULT_DELIVERY_TIERS = [
  { max_order: 10, delivery_days: 7 },
  { max_order: 50, delivery_days: 15 },
  { max_order: 0, delivery_days: 30 },
];

const deliveryTiersToDrafts = (tiers: Array<{ max_order?: number; delivery_days?: number }>) =>
  tiers.map((t) => ({
    max_order: String(t.max_order ?? ""),
    delivery_days: String(t.delivery_days ?? ""),
  }));

const draftsToDeliveryTiers = (drafts: Array<{ max_order: string; delivery_days: string }>) =>
  drafts
    .map((d) => ({
      max_order: d.max_order === "" ? 0 : parseInt(d.max_order, 10) || 0,
      delivery_days: d.delivery_days === "" ? 0 : parseInt(d.delivery_days, 10) || 0,
    }))
    .filter((d) => d.delivery_days > 0);

const MAX_DELIVERY_TIERS = 3;

const deliveryTierLabel = (index: number, total: number) => {
  if (index === total - 1 && total > 1) {
    return `第${index + 1}档（数量填 0 表示剩余起订量）`;
  }
  return `第${index + 1}档`;
};

export default function ProductConfig() {
  const [config, setConfig] = useState<Record<string, any>>({});
  const configRef = useRef<Record<string, any>>({});
  /** 用户正在编辑时，禁止后台 config 刷新覆盖本地 state */
  const hasLocalEditsRef = useRef(false);
  const markLocalEdit = () => {
    hasLocalEditsRef.current = true;
  };
  const clearLocalEdit = () => {
    hasLocalEditsRef.current = false;
  };
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [attrEditorOpen, setAttrEditorOpen] = useState(false);
  const [editingAttrName, setEditingAttrName] = useState("");
  const [editingAttrText, setEditingAttrText] = useState("");
  const [specFormOpen, setSpecFormOpen] = useState(false);
  const [isSpecEditMode, setIsSpecEditMode] = useState(false);
  const [originalSpecName, setOriginalSpecName] = useState("");
  const [specForm, setSpecForm] = useState({
    group: "",
    name: "",
    container_id: "",
    valuesText: "",
    defaultValuesText: "",
    max_select: 2,
    type: "checkbox",
    interaction: "checkbox_grid",
    sale_attribute_value: "",
    enable_sale_attribute: false,
    enable_spec_image: false,
    image_subdir: "SKU",
  });

  const [attrFormOpen, setAttrFormOpen] = useState(false);
  const [isAttrEditMode, setIsAttrEditMode] = useState(false);
  const [originalAttrName, setOriginalAttrName] = useState("");
  const [attrForm, setAttrForm] = useState({
    name: "",
    container_id: "",
    select_type: "tag",
    valuesText: "",
    fill_count: "1",
    enabled: true,
  });

  const [fetchingAttrs, setFetchingAttrs] = useState(false);
  const [fetchingSpecs, setFetchingSpecs] = useState(false);
  const [groupNameDrafts, setGroupNameDrafts] = useState<Record<string, string>>({});
  const [attrFillCountDrafts, setAttrFillCountDrafts] = useState<Record<string, string>>({});
  const [specFillCountDrafts, setSpecFillCountDrafts] = useState<Record<string, string>>({});
  const [priceUnitDraft, setPriceUnitDraft] = useState("");
  const [deliveryTierDrafts, setDeliveryTierDrafts] = useState(
    deliveryTiersToDrafts(DEFAULT_DELIVERY_TIERS),
  );

  const isAdminSession = useMemo(() => {
    try {
      return (localStorage.getItem("admin_console_logged_in") || "") === "1";
    } catch {
      return false;
    }
  }, []);

  // 加载配置（强制从服务端拉取，避免 localStorage 缓存缺少新字段）
  useEffect(() => {
    loadConfig(true);
  }, []);

  const syncPriceDeliveryDrafts = (root: Record<string, any>) => {
    const saved = String(root?.price?.price_unit ?? "").trim();
    setPriceUnitDraft(isValidPriceUnit(saved) ? saved : DEFAULT_PRICE_UNIT);
    const tiers = root?.delivery?.ladder_delivery?.length
      ? root.delivery.ladder_delivery
      : DEFAULT_DELIVERY_TIERS;
    setDeliveryTierDrafts(deliveryTiersToDrafts(tiers));
  };

  const mergePriceDeliveryIntoConfig = (root: Record<string, any>) => {
    const unit = priceUnitDraft.trim();
    const next = { ...root };
    next.price = {
      ...(next.price || {}),
      price_unit: isValidPriceUnit(unit) ? unit : DEFAULT_PRICE_UNIT,
    };
    next.delivery = {
      ...(next.delivery || {}),
      ladder_delivery: draftsToDeliveryTiers(deliveryTierDrafts),
    };
    return next;
  };

  useEffect(() => {
    return subscribeConfigUpdates(() => {
      if (hasLocalEditsRef.current) return;
      const cached = configApi.getCached();
      const root = cached?.data || {};
      if (!root || typeof root !== "object" || !Object.keys(root).length) return;
      configRef.current = root;
      setConfig(root);
      syncPriceDeliveryDrafts(root);
    });
  }, []);

  const loadConfig = async (forceRefresh: boolean = false) => {
    try {
      setLoading(true);
      const result = await configApi.get(forceRefresh);
      const root = result?.data || {};
      configRef.current = root;
      clearLocalEdit();
      setConfig(root);
      syncPriceDeliveryDrafts(root);
    } catch (e: any) {
      toast.error("加载配置失败: " + (e.message || ""));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const map = config?.group_urls?.group_url_map || {};
    const next: Record<string, string> = {};
    Object.keys(map).forEach((k) => {
      next[k] = groupNameDrafts[k] ?? k;
    });
    setGroupNameDrafts(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config?.group_urls?.group_url_map]);

  useEffect(() => {
    const allAttrs = config?.attributes?.all_attributes || {};
    const countRule = config?.attributes?.count_rule || {};
    const next: Record<string, string> = {};
    Object.keys(allAttrs).forEach((name) => {
      const cur = attrFillCountDrafts[name];
      next[name] = cur !== undefined ? cur : String(Number(countRule[name] || 1));
    });
    setAttrFillCountDrafts(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config?.attributes?.all_attributes, config?.attributes?.count_rule]);

  useEffect(() => {
    const groupMap = config?.group_urls?.group_url_map || {};
    const specsByGroup = config?.attributes?.specifications_by_group || {};
    const aliasMap = config?.attributes?.specification_group_alias || {};
    const next: Record<string, string> = {};
    Object.keys(groupMap).forEach((groupName) => {
      const sourceGroup = aliasMap[groupName] || groupName;
      const specs = specsByGroup[sourceGroup] || specsByGroup[groupName] || {};
      Object.entries(specs).forEach(([specName, item]: [string, any]) => {
        const key = `${groupName}::${specName}`;
        const cur = specFillCountDrafts[key];
        next[key] = cur !== undefined ? cur : String(Number(item?.max_select || 1));
      });
    });
    setSpecFillCountDrafts(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config?.group_urls?.group_url_map, config?.attributes?.specifications_by_group, config?.attributes?.specification_group_alias]);

  const persistConfig = async (nextConfig: Record<string, any>, successMessage: string) => {
    const payload = syncAllCategorySpecs(nextConfig);
    configRef.current = payload;
    setConfig(payload);
    const saved = await configApi.update(payload);
    const root = saved?.data || payload;
    verifySpecFieldsPersisted(payload, root);
    configRef.current = root;
    clearLocalEdit();
    setConfig(root);
    syncPriceDeliveryDrafts(root);
    toast.success(successMessage);
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      const merged = mergePriceDeliveryIntoConfig(configRef.current);
      configRef.current = merged;
      setConfig(merged);
      await persistConfig(merged, "配置已保存");
    } catch (e: any) {
      toast.error("保存失败: " + (e.message || ""));
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    try {
      await configApi.reset();
      await loadConfig();
      toast.success("已重置为默认配置");
    } catch (e: any) {
      toast.error("重置失败: " + (e.message || ""));
    }
  };

  // 便捷更新嵌套配置（同步写入 ref，避免「保存配置」读到过期 state）
  const updateConfig = (path: string, value: any) => {
    markLocalEdit();
    setConfig((prev) => {
      const newConfig = { ...prev };
      const keys = path.split(".");
      let obj: any = newConfig;
      for (let i = 0; i < keys.length - 1; i++) {
        if (!obj[keys[i]]) obj[keys[i]] = {};
        obj[keys[i]] = { ...obj[keys[i]] };
        obj = obj[keys[i]];
      }
      obj[keys[keys.length - 1]] = value;
      configRef.current = newConfig;
      return newConfig;
    });
  };

  const patchConfig = (patcher: (prev: Record<string, any>) => Record<string, any>) => {
    markLocalEdit();
    setConfig((prev) => {
      const newConfig = patcher(prev);
      configRef.current = newConfig;
      return newConfig;
    });
  };

  const openAttrEditor = (attr: any) => {
    setEditingAttrName(attr.name);
    setEditingAttrText(Array.isArray(attr.values) ? attr.values.join("\n") : "");
    setAttrEditorOpen(true);
  };

  const normalizeAttrEditorText = (input: string) => {
    const values = input
      .split(/\r?\n/)
      .map((v) => v.trim())
      .filter((v) => v.length > 0);
    const unique = Array.from(new Set(values));
    return unique.join("\n");
  };

  const convertCommaToLines = () => {
    const items = editingAttrText
      .split(/[，,]/)
      .map((v) => v.trim())
      .filter((v) => v.length > 0);
    setEditingAttrText(items.join("\n"));
    toast.success("已按逗号分隔转换为多行");
  };

  const dedupeAndCleanLines = () => {
    const normalized = normalizeAttrEditorText(editingAttrText);
    setEditingAttrText(normalized);
    toast.success("已去重并清理空行");
  };

  const saveAttrEditor = () => {
    const values = normalizeAttrEditorText(editingAttrText)
      .split(/\r?\n/)
      .filter((v) => v.length > 0);

    const allAttrs = { ...(config?.attributes?.all_attributes || {}) };
    const target = { ...(allAttrs?.[editingAttrName] || {}) };
    target.values = values;
    allAttrs[editingAttrName] = target;
    updateConfig("attributes.all_attributes", allAttrs);

    setAttrEditorOpen(false);
    toast.success(`已更新「${editingAttrName}」可选值`);
  };

  const openAddAttrForm = () => {
    setIsAttrEditMode(false);
    setOriginalAttrName("");
    setAttrForm({
      name: "",
      container_id: "",
      select_type: "tag",
      valuesText: "",
      fill_count: "1",
      enabled: true,
    });
    setAttrFormOpen(true);
  };

  const openEditAttrForm = (attr: any) => {
    setIsAttrEditMode(true);
    setOriginalAttrName(attr.name);
    setAttrForm({
      name: attr.name || "",
      container_id: attr.container_id || "",
      select_type: attr.select_type || "tag",
      valuesText: Array.isArray(attr.values) ? attr.values.join("\n") : "",
      fill_count: String(Number(attr.fill_count || 1)),
      enabled: !!attr.enabled,
    });
    setAttrFormOpen(true);
  };

  const saveAttrForm = () => {
    const name = attrForm.name.trim();
    if (!name) {
      toast.error("请输入属性名");
      return;
    }

    const allAttrs = { ...(config?.attributes?.all_attributes || {}) };
    if (!isAttrEditMode && allAttrs[name]) {
      toast.error("属性名已存在");
      return;
    }

    const values = normalizeAttrEditorText(attrForm.valuesText)
      .split(/\r?\n/)
      .filter((v) => v.length > 0);
    const fillCount = Math.max(1, Number(attrForm.fill_count || 1));

    const nextItem = {
      ...(allAttrs[originalAttrName] || {}),
      container_id: attrForm.container_id.trim(),
      select_type: attrForm.select_type.trim() || "tag",
      values,
    };

    if (isAttrEditMode && originalAttrName && originalAttrName !== name) {
      delete allAttrs[originalAttrName];
    }
    allAttrs[name] = nextItem;
    updateConfig("attributes.all_attributes", allAttrs);

    const nextCountRule = { ...(config?.attributes?.count_rule || {}) };
    if (isAttrEditMode && originalAttrName && originalAttrName !== name) {
      delete nextCountRule[originalAttrName];
    }
    nextCountRule[name] = fillCount;
    updateConfig("attributes.count_rule", nextCountRule);

    const skipAttrs = [...(config?.attributes?.skip_attrs || [])];
    const oldIdx = originalAttrName ? skipAttrs.indexOf(originalAttrName) : -1;
    if (oldIdx >= 0) skipAttrs.splice(oldIdx, 1);
    if (!attrForm.enabled && !skipAttrs.includes(name)) {
      skipAttrs.push(name);
    }
    updateConfig("attributes.skip_attrs", skipAttrs);

    setAttrFormOpen(false);
    toast.success(isAttrEditMode ? "属性已更新" : "属性已新增");
  };

  const deleteAttr = (name: string) => {
    const allAttrs = { ...(config?.attributes?.all_attributes || {}) };
    if (!allAttrs[name]) return;
    delete allAttrs[name];
    updateConfig("attributes.all_attributes", allAttrs);

    const skipAttrs = [...(config?.attributes?.skip_attrs || [])].filter((x) => x !== name);
    updateConfig("attributes.skip_attrs", skipAttrs);

    const nextCountRule = { ...(config?.attributes?.count_rule || {}) };
    if (Object.prototype.hasOwnProperty.call(nextCountRule, name)) {
      delete nextCountRule[name];
      updateConfig("attributes.count_rule", nextCountRule);
    }

    toast.success(`已删除属性「${name}」`);
  };

  const updateAttrFillCount = (name: string, nextCountRaw: string) => {
    const parsed = Number(nextCountRaw);
    const count = Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 1;
    const nextCountRule = { ...(config?.attributes?.count_rule || {}) };
    nextCountRule[name] = count;
    updateConfig("attributes.count_rule", nextCountRule);
  };

  const openAddSpecForm = (groupName?: string) => {
    setIsSpecEditMode(false);
    setOriginalSpecName("");
    setSpecForm({
      group: groupName || "",
      name: "",
      container_id: "",
      valuesText: "",
      defaultValuesText: "",
      max_select: 2,
      type: "checkbox",
      interaction: "checkbox_grid",
      sale_attribute_value: "",
      enable_sale_attribute: false,
      enable_spec_image: false,
      image_subdir: "SKU",
    });
    setSpecFormOpen(true);
  };

  const openEditSpecForm = (groupName: string, name: string, spec: any) => {
    setIsSpecEditMode(true);
    setOriginalSpecName(name);
    const interaction = spec?.interaction || (spec?.type === "value_rows" ? "value_rows" : "checkbox_grid");
    setSpecForm({
      group: groupName || "",
      name,
      container_id: spec?.container_id || "",
      valuesText: Array.isArray(spec?.values_pool) ? spec.values_pool.join("\n") : "",
      defaultValuesText: Array.isArray(spec?.default_values) ? spec.default_values.join("\n") : "",
      max_select: Number(spec?.max_select || 2),
      type: spec?.type || (interaction === "value_rows" ? "value_rows" : "checkbox"),
      interaction,
      sale_attribute_value: spec?.sale_attribute_value || "",
      enable_sale_attribute: resolveEnableSaleAttribute(spec, name),
      enable_spec_image: !!spec?.enable_spec_image,
      image_subdir: spec?.image_subdir || (name === "颜色" ? "SKU" : name === "样式" ? "样式" : "SKU"),
    });
    setSpecFormOpen(true);
  };

  const saveSpecForm = async () => {
    const groupName = specForm.group.trim();
    if (!groupName) {
      toast.error("请选择组别");
      return;
    }

    const name = specForm.name.trim();
    if (!name) {
      toast.error("请输入规格名");
      return;
    }

    const maxSelect = Number(specForm.max_select || 1);
    if (maxSelect <= 0) {
      toast.error("最多选择数量必须大于 0");
      return;
    }

    const prev = configRef.current || {};
    const allGroupSpecs = { ...(prev?.attributes?.specifications_by_group || {}) };
    const aliasMap = { ...(prev?.attributes?.specification_group_alias || {}) };
    const sourceGroup = (aliasMap[groupName] && aliasMap[groupName] !== groupName) ? aliasMap[groupName] : groupName;
    const baseSpecs = { ...(allGroupSpecs[sourceGroup] || {}) };
    const allSpecs = sourceGroup === groupName ? baseSpecs : { ...baseSpecs };

    // 组别原本共用其他组时，编辑即自动拆分为独立配置
    if (sourceGroup !== groupName) {
      aliasMap[groupName] = groupName;
      allGroupSpecs[groupName] = { ...allSpecs };
    }

    if (!isSpecEditMode && allSpecs[name]) {
      toast.error("规格名已存在");
      return;
    }

    const valuesPool = normalizeAttrEditorText(specForm.valuesText)
      .split(/\r?\n/)
      .map((v) => v.trim())
      .filter((v) => v.length > 0);
    const defaultValues = normalizeAttrEditorText(specForm.defaultValuesText)
      .split(/\r?\n/)
      .map((v) => v.trim())
      .filter((v) => v.length > 0)
      .filter((v) => valuesPool.includes(v));

    const isValueRows = specForm.interaction === "value_rows";
    const interaction = isValueRows ? "value_rows" : "checkbox_grid";
    const fillValues = isValueRows
      ? normalizeAttrEditorText(specForm.defaultValuesText)
          .split(/\r?\n/)
          .map((v) => v.trim())
          .filter((v) => v.length > 0)
      : defaultValues;

    const nextItem = {
      ...(allSpecs[originalSpecName] || {}),
      container_id: specForm.container_id.trim(),
      values_pool: isValueRows ? fillValues : valuesPool,
      default_values: isValueRows ? fillValues : defaultValues,
      max_select: isValueRows ? Math.max(1, fillValues.length) : maxSelect,
      type: isValueRows ? "value_rows" : (specForm.type.trim() || "checkbox"),
      interaction,
      sale_attribute_value: deriveSaleAttributeValue(
        specForm.container_id,
        (allSpecs[originalSpecName] || {}).sale_attribute_value,
      ),
      enable_sale_attribute: !!specForm.enable_sale_attribute,
      enable_spec_image: isValueRows ? specForm.enable_spec_image : false,
      image_subdir: isValueRows ? (specForm.image_subdir.trim() || "SKU") : "",
    };

    if (isSpecEditMode && originalSpecName && originalSpecName !== name) {
      delete allSpecs[originalSpecName];
    }
    allSpecs[name] = nextItem;

    allGroupSpecs[groupName] = allSpecs;
    let nextConfig: Record<string, any> = {
      ...prev,
      attributes: {
        ...(prev.attributes || {}),
        specifications_by_group: allGroupSpecs,
        specification_group_alias: aliasMap,
      },
    };
    nextConfig = syncCategorySpecsForGroup(nextConfig, groupName, allSpecs);

    try {
      setSaving(true);
      await persistConfig(nextConfig, isSpecEditMode ? "规格已保存" : "规格已新增");
      setSpecFormOpen(false);
    } catch (e: any) {
      toast.error("保存规格失败: " + (e.message || ""));
    } finally {
      setSaving(false);
    }
  };

  const deleteSpec = (groupName: string, name: string) => {
    const allGroupSpecs = { ...(config?.attributes?.specifications_by_group || {}) };
    const aliasMap = { ...(config?.attributes?.specification_group_alias || {}) };
    const sourceGroup = (aliasMap[groupName] && aliasMap[groupName] !== groupName) ? aliasMap[groupName] : groupName;
    const baseSpecs = { ...(allGroupSpecs[sourceGroup] || {}) };
    const allSpecs = sourceGroup === groupName ? baseSpecs : { ...baseSpecs };
    if (!allSpecs[name]) return;
    delete allSpecs[name];

    if (sourceGroup !== groupName) {
      aliasMap[groupName] = groupName;
    }
    allGroupSpecs[groupName] = allSpecs;
    updateConfig("attributes.specifications_by_group", allGroupSpecs);
    updateConfig("attributes.specification_group_alias", aliasMap);
    toast.success(`已删除组别「${groupName}」下规格「${name}」`);
  };

  const updateSpecFillCount = (groupName: string, name: string, nextCountRaw: string) => {
    const parsed = Number(nextCountRaw);
    const count = Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : 1;
    const allGroupSpecs = { ...(config?.attributes?.specifications_by_group || {}) };
    const aliasMap = { ...(config?.attributes?.specification_group_alias || {}) };
    const sourceGroup = (aliasMap[groupName] && aliasMap[groupName] !== groupName) ? aliasMap[groupName] : groupName;
    const baseSpecs = { ...(allGroupSpecs[sourceGroup] || {}) };
    const allSpecs = sourceGroup === groupName ? baseSpecs : { ...baseSpecs };
    if (!allSpecs[name]) return;
    if (sourceGroup !== groupName) aliasMap[groupName] = groupName;
    allSpecs[name] = { ...allSpecs[name], max_select: count };
    allGroupSpecs[groupName] = allSpecs;
    updateConfig("attributes.specifications_by_group", allGroupSpecs);
    updateConfig("attributes.specification_group_alias", aliasMap);
  };

  const addGroupUrl = () => {
    const map = { ...(config?.group_urls?.group_url_map || {}) };
    let idx = Object.keys(map).length + 1;
    let name = `新组别${idx}`;
    while (map[name]) {
      idx += 1;
      name = `新组别${idx}`;
    }
    map[name] = "";
    updateConfig("group_urls.group_url_map", map);
    toast.success(`已新增组别：${name}`);
  };

  const handleFetchAttributes = async () => {
    try {
      setFetchingAttrs(true);
      const res: any = await configApi.fetchAttributesFromPlatform();
      const payload = res?.data || res;
      toast.success(payload?.message || "属性抓取完成");
      await loadConfig(true);
    } catch (e: any) {
      toast.error(e?.message || "抓取属性失败");
    } finally {
      setFetchingAttrs(false);
    }
  };

  const handleFetchSpecifications = async () => {
    try {
      setFetchingSpecs(true);
      const res: any = await configApi.fetchSpecificationsFromPlatform();
      const payload = res?.data || res;
      toast.success(payload?.message || "规格抓取完成");
      await loadConfig(true);
    } catch (e: any) {
      toast.error(e?.message || "抓取规格失败");
    } finally {
      setFetchingSpecs(false);
    }
  };

  // 价格阶梯
  const priceTiers = config?.price?.ladder_min_orders?.map((qty: number, i: number) => ({
    minQty: qty,
    factorLow: config?.price?.ladder_factor_ranges?.[i]?.[0] ?? 1.0,
    factorHigh: config?.price?.ladder_factor_ranges?.[i]?.[1] ?? 1.5,
  })) || [];

  // 属性映射
  const attributes = config?.attributes?.all_attributes
    ? Object.entries(config.attributes.all_attributes).map(([name, item]: [string, any]) => ({
        name,
        container_id: item.container_id || "",
        select_type: item.select_type || "tag",
        values: item.values || [],
        fill_count: Number(config?.attributes?.count_rule?.[name] || 1),
        enabled: !config?.attributes?.skip_attrs?.includes(name),
      }))
    : [];

  const groupedSpecifications = (() => {
    const groupMap = config?.group_urls?.group_url_map || {};
    const specsByGroup = config?.attributes?.specifications_by_group || {};
    const aliasMap = config?.attributes?.specification_group_alias || {};
    const legacySpecs = config?.attributes?.specifications || {};
    const hasGrouped = Object.keys(specsByGroup).length > 0;
    const groupNames = Object.keys(groupMap);

    return groupNames.map((groupName: string, index: number) => {
      const sourceGroup = aliasMap?.[groupName] || groupName;
      const fallbackLegacy = (!hasGrouped && index === 0) ? legacySpecs : {};
      const rawSpecs = specsByGroup?.[sourceGroup] || (sourceGroup === groupName ? specsByGroup?.[groupName] : null) || fallbackLegacy;
      const specs = Object.entries(rawSpecs || {}).map(([name, item]: [string, any]) => ({
        name,
        container_id: item?.container_id || "",
        values_pool: item?.values_pool || [],
        default_values: item?.default_values || [],
        max_select: item?.max_select || 1,
        type: item?.type || "checkbox",
        interaction: item?.interaction || (item?.type === "value_rows" ? "value_rows" : "checkbox_grid"),
        sale_attribute_value: item?.sale_attribute_value || "",
        enable_sale_attribute: resolveEnableSaleAttribute(item, name),
        enable_spec_image: !!item?.enable_spec_image,
        image_subdir: item?.image_subdir || "",
      }));
      return {
        groupName,
        sourceGroup,
        shared: !!sourceGroup && sourceGroup !== groupName,
        specs,
      };
    });
  })();

  const totalSpecs = groupedSpecifications.reduce((sum: number, g: any) => sum + (g.specs?.length || 0), 0);

  return (
    <div className="p-8">
      {/* Page Header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-1">
          <span>产品上传</span>
          <ChevronRight className="w-3.5 h-3.5" />
          <span className="text-foreground">配置管理</span>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground">配置管理</h1>
            <p className="text-sm text-muted-foreground mt-1">管理发品系统的全局配置、属性映射和价格模板</p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={handleReset} className="gap-2">
              <RefreshCw className="w-4 h-4" />
              重置
            </Button>
            <Button onClick={handleSave} disabled={saving} className="gap-2">
              <Save className="w-4 h-4" />
              {saving ? "保存中..." : "保存配置"}
            </Button>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-64 text-muted-foreground">加载中...</div>
      ) : (
        <Tabs defaultValue="urls" className="space-y-6">
          <TabsList className="bg-muted/50">
            <TabsTrigger value="urls" className="gap-2">
              <Globe className="w-3.5 h-3.5" />
              URL配置
            </TabsTrigger>
            <TabsTrigger value="paths" className="gap-2">
              <FolderOpen className="w-3.5 h-3.5" />
              路径配置
            </TabsTrigger>
            <TabsTrigger value="price" className="gap-2">
              <DollarSign className="w-3.5 h-3.5" />
              价格模板
            </TabsTrigger>
            <TabsTrigger value="attrs" className="gap-2">
              <Tag className="w-3.5 h-3.5" />
              属性配置
            </TabsTrigger>
            <TabsTrigger value="specs" className="gap-2">
              <Tag className="w-3.5 h-3.5" />
              商品规格
            </TabsTrigger>
            <TabsTrigger value="cookie" className="gap-2">
              <Key className="w-3.5 h-3.5" />
              Cookie管理
            </TabsTrigger>
            {isAdminSession ? (
              <TabsTrigger value="payment" className="gap-2">
                <Settings className="w-3.5 h-3.5" />
                支付配置
              </TabsTrigger>
            ) : null}
          </TabsList>

          {/* URL Config */}
          <TabsContent value="urls">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">平台URL配置</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">默认发品链接</Label>
                  <div className="col-span-2">
                    <Input
                      value={config?.group_urls?.default_posting_url || ""}
                      onChange={(e) => updateConfig("group_urls.default_posting_url", e.target.value)}
                      className="text-sm font-mono"
                    />
                  </div>
                  <Button variant="ghost" size="sm" className="gap-1.5 text-xs" onClick={() => {
                    navigator.clipboard.writeText(config?.group_urls?.default_posting_url || "");
                    toast.info("已复制");
                  }}>
                    <Copy className="w-3.5 h-3.5" />
                    复制
                  </Button>
                </div>
                <Separator />
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <Label className="text-sm text-muted-foreground block">分组发品链接</Label>
                    <Button size="sm" variant="outline" className="gap-1.5" onClick={addGroupUrl}>
                      <Plus className="w-3.5 h-3.5" />
                      新增组别
                    </Button>
                  </div>
                  <div className="space-y-2">
                    {Object.entries(config?.group_urls?.group_url_map || {}).map(([group, url]: [string, any]) => (
                      <div key={group} className="grid grid-cols-4 gap-4 items-center">
                        <Input
                          value={groupNameDrafts[group] ?? group}
                          className="text-sm"
                          onFocus={() => {
                            const cur = groupNameDrafts[group] ?? group;
                            if (/^新组别\d+$/.test(String(cur))) {
                              setGroupNameDrafts((prev) => ({ ...prev, [group]: "" }));
                            }
                          }}
                          onChange={(e) => {
                            const v = e.target.value;
                            setGroupNameDrafts((prev) => ({ ...prev, [group]: v }));
                          }}
                          onBlur={() => {
                            const draft = String(groupNameDrafts[group] ?? "").trim();
                            if (!draft) {
                              // 空值回退（新组别会回退为原key，避免丢项）
                              setGroupNameDrafts((prev) => ({ ...prev, [group]: group }));
                              return;
                            }
                            if (draft === group) return;

                            const map = { ...(config?.group_urls?.group_url_map || {}) };
                            if (map[draft] && draft !== group) {
                              toast.error("组别名称已存在");
                              setGroupNameDrafts((prev) => ({ ...prev, [group]: group }));
                              return;
                            }

                            map[draft] = map[group];
                            delete map[group];
                            updateConfig("group_urls.group_url_map", map);

                            const specsByGroup = { ...(config?.attributes?.specifications_by_group || {}) };
                            if (Object.prototype.hasOwnProperty.call(specsByGroup, group)) {
                              specsByGroup[draft] = specsByGroup[group];
                              delete specsByGroup[group];
                              updateConfig("attributes.specifications_by_group", specsByGroup);
                            }

                            const aliasMap = { ...(config?.attributes?.specification_group_alias || {}) };
                            const currentAliasSource = aliasMap[group] || group;
                            delete aliasMap[group];
                            aliasMap[draft] = currentAliasSource === group ? draft : currentAliasSource;
                            Object.keys(aliasMap).forEach((k) => {
                              if (aliasMap[k] === group) aliasMap[k] = draft;
                            });
                            updateConfig("attributes.specification_group_alias", aliasMap);

                            setGroupNameDrafts((prev) => {
                              const next = { ...prev };
                              delete next[group];
                              next[draft] = draft;
                              return next;
                            });
                          }}
                        />
                        <div className="col-span-2">
                          <Input
                            value={url}
                            onChange={(e) => {
                              const newMap = { ...config.group_urls.group_url_map, [group]: e.target.value };
                              updateConfig("group_urls.group_url_map", newMap);
                            }}
                            className="text-sm font-mono"
                          />
                        </div>
                        <Button variant="ghost" size="sm" className="text-destructive" onClick={() => {
                          const newMap = { ...config.group_urls.group_url_map };
                          delete newMap[group];
                          updateConfig("group_urls.group_url_map", newMap);

                          const specsByGroup = { ...(config?.attributes?.specifications_by_group || {}) };
                          if (Object.prototype.hasOwnProperty.call(specsByGroup, group)) {
                            delete specsByGroup[group];
                            updateConfig("attributes.specifications_by_group", specsByGroup);
                          }

                          const aliasMap = { ...(config?.attributes?.specification_group_alias || {}) };
                          delete aliasMap[group];
                          Object.keys(aliasMap).forEach((k) => {
                            if (aliasMap[k] === group) aliasMap[k] = k;
                          });
                          updateConfig("attributes.specification_group_alias", aliasMap);
                        }}>
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Specification Config */}
          <TabsContent value="specs">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">商品规格配置</CardTitle>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{totalSpecs} 个规格</Badge>
                    <Button
                      size="sm"
                      variant="outline"
                      className="gap-1"
                      onClick={handleFetchSpecifications}
                      disabled={fetchingSpecs}
                    >
                      <RefreshCw className={`w-3.5 h-3.5 ${fetchingSpecs ? "animate-spin" : ""}`} />
                      {fetchingSpecs ? "获取中..." : "获取规格"}
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-5">
                  {groupedSpecifications.map((groupItem: any) => (
                    <div key={groupItem.groupName} className="rounded-lg border border-border/60 p-3 space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Label className="text-sm font-medium">{groupItem.groupName}</Label>
                          {groupItem.shared ? (
                            <Badge variant="secondary">共用自：{groupItem.sourceGroup}</Badge>
                          ) : null}
                          <Badge variant="outline">{groupItem.specs.length} 个规格</Badge>
                        </div>
                        <Button size="sm" className="gap-1" onClick={() => openAddSpecForm(groupItem.groupName)}>
                          <Plus className="w-3.5 h-3.5" />
                          新增规格
                        </Button>
                      </div>

                      <div className="grid grid-cols-12 gap-4 text-xs font-medium text-muted-foreground px-2">
                        <span className="col-span-2">规格名</span>
                        <span className="col-span-2">类型</span>
                        <span className="col-span-2">容器ID</span>
                        <span className="col-span-1">填入数量</span>
                        <span className="col-span-2">值池/填充值</span>
                        <span className="col-span-1">顶部项</span>
                        <span className="col-span-1">规格图</span>
                        <span className="col-span-1">操作</span>
                      </div>
                      {groupItem.specs.map((spec: any) => (
                        <div key={`${groupItem.groupName}-${spec.name}`} className="grid grid-cols-12 gap-4 items-center">
                          <button
                            type="button"
                            className="col-span-2 text-left text-sm underline-offset-2 hover:underline"
                            onClick={() => openEditSpecForm(groupItem.groupName, spec.name, spec)}
                            title="点击编辑规格"
                          >
                            {spec.name}
                          </button>
                          <div className="col-span-2 text-xs text-muted-foreground">
                            {spec.interaction === "value_rows" ? "输入行+图片" : "复选框"}
                          </div>
                          <Input value={spec.container_id} className="col-span-2 text-xs font-mono" readOnly />
                          <Input
                            type="number"
                            min={1}
                            value={specFillCountDrafts[`${groupItem.groupName}::${spec.name}`] ?? String(spec.max_select)}
                            className="col-span-1 text-xs"
                            onChange={(e) => {
                              const key = `${groupItem.groupName}::${spec.name}`;
                              setSpecFillCountDrafts((prev) => ({ ...prev, [key]: e.target.value }));
                            }}
                            onBlur={(e) => {
                              const key = `${groupItem.groupName}::${spec.name}`;
                              updateSpecFillCount(groupItem.groupName, spec.name, e.target.value);
                              const normalized = String(Math.max(1, Number(e.target.value || 1)));
                              setSpecFillCountDrafts((prev) => ({ ...prev, [key]: normalized }));
                            }}
                          />
                          <button
                            type="button"
                            className="col-span-2 text-left text-xs text-muted-foreground truncate hover:text-foreground"
                            onClick={() => openEditSpecForm(groupItem.groupName, spec.name, spec)}
                            title="点击编辑规格值"
                          >
                            {(spec.interaction === "value_rows"
                              ? (spec.default_values || spec.values_pool)
                              : spec.values_pool
                            ).join(", ") || "无"}
                          </button>
                          <div
                            className="col-span-1 text-xs"
                            title={spec.enable_sale_attribute ? "发品时勾选顶部规格项" : "发品时不勾选顶部规格项"}
                          >
                            {spec.enable_sale_attribute ? (
                              <Badge variant="secondary">开</Badge>
                            ) : (
                              <span className="text-muted-foreground">关</span>
                            )}
                          </div>
                          <div
                            className="col-span-1 text-xs text-muted-foreground truncate"
                            title={spec.enable_spec_image ? `目录: ${spec.image_subdir || "SKU"}` : "未开启规格图"}
                          >
                            {spec.enable_spec_image ? spec.image_subdir || "SKU" : "-"}
                          </div>
                          <div className="col-span-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-destructive hover:text-destructive"
                              onClick={() => deleteSpec(groupItem.groupName, spec.name)}
                            >
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          </div>
                        </div>
                      ))}
                      {groupItem.specs.length === 0 ? (
                        <div className="text-xs text-muted-foreground px-2 py-2">该组别暂无规格配置</div>
                      ) : null}
                    </div>
                  ))}
                  {groupedSpecifications.length === 0 ? (
                    <div className="text-sm text-muted-foreground">请先在“URL配置”里添加分组发品链接组别</div>
                  ) : null}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Path Config */}
          <TabsContent value="paths">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">文件路径配置</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">项目资料根目录</Label>
                  <div className="col-span-3 space-y-2">
                    <Input
                      // 使用空串兜底，避免用户清空输入时被默认值立即“抢占回填”
                      value={config?.paths?.project_files_root ?? ""}
                      onChange={(e) => updateConfig("paths.project_files_root", e.target.value)}
                      className="text-sm font-mono"
                      placeholder="例如：D:\\Alibaba"
                    />
                    <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                      项目资料文件存放处。保存配置后，系统会自动把其他路径统一到该目录下并自动创建子目录。
                    </div>
                  </div>
                </div>
                <Separator />
                {[
                  { key: "paths.primary_image_dir", label: "首图文件夹" },
                  { key: "paths.main_image_dir", label: "主图文件夹" },
                  { key: "paths.exceptional_main_image_dir", label: "异常主图文件夹" },
                  { key: "paths.title_excel_path", label: "标题Excel路径" },
                  { key: "paths.cookie_file", label: "Cookie文件" },
                  { key: "paths.download_save_dir", label: "下载保存目录" },
                ].map((item) => (
                  <div key={item.key} className="grid grid-cols-4 gap-4 items-center">
                    <Label className="text-sm text-right text-muted-foreground">{item.label}</Label>
                    <div className="col-span-3">
                      <Input
                        value={item.key.split(".").reduce((obj: any, k) => obj?.[k], config) || ""}
                        onChange={(e) => updateConfig(item.key, e.target.value)}
                        className="text-sm font-mono"
                        placeholder={`请输入${item.label}路径`}
                      />
                    </div>
                  </div>
                ))}

                <Separator />
                <div>
                  <Label className="text-sm text-muted-foreground mb-2 block">详情模块路径配置</Label>
                  <div className="space-y-3">
                    {[
                      { key: "paths.detail_scene_image_dir", label: "详情-场景图目录" },
                      { key: "paths.detail_detail_image_dir", label: "详情-细节图目录" },
                      { key: "paths.detail_company_image_root_dir", label: "详情-公司图片根目录" },
                      { key: "paths.detail_company_intro_file", label: "详情-公司介绍文件", placeholder: "公司介绍文件（txt）" },
                      { key: "paths.detail_faq_file", label: "详情-FAQs文件", placeholder: "FAQs文件（.txt，每行一个QA为一组）" },
                      { key: "detail.selling_points_excel", label: "详情-卖点Excel路径" },
                    ].map((item: any) => (
                      <div key={item.key} className="grid grid-cols-4 gap-4 items-center">
                        <Label className="text-sm text-right text-muted-foreground">{item.label}</Label>
                        <div className="col-span-3">
                          <Input
                            value={item.key.split(".").reduce((obj: any, k: string) => obj?.[k], config) || ""}
                            onChange={(e) => updateConfig(item.key, e.target.value)}
                            className="text-sm font-mono"
                            placeholder={item.placeholder || `请输入${item.label}`}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Price Template */}
          <TabsContent value="price">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">阶梯价格配置</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">汇率 (CNY/USD)</Label>
                  <Input
                    type="number"
                    step="0.01"
                    value={config?.price?.exchange_rate || 7.2}
                    onChange={(e) => updateConfig("price.exchange_rate", parseFloat(e.target.value) || 7.2)}
                    className="text-sm"
                  />
                  <Label className="text-sm text-right text-muted-foreground">随机浮动</Label>
                  <Switch
                    checked={config?.price?.enable_random_float ?? true}
                    onCheckedChange={(v) => updateConfig("price.enable_random_float", v)}
                  />
                </div>
                <Separator />
                <div className="space-y-3">
                  <div className="grid grid-cols-4 gap-4 text-xs font-medium text-muted-foreground px-2">
                    <span>起订量</span>
                    <span>倍率下限</span>
                    <span>倍率上限</span>
                    <span>操作</span>
                  </div>
                  {priceTiers.map((tier: any, i: number) => (
                    <div key={i} className="grid grid-cols-4 gap-4 items-center">
                      <Input type="number" value={tier.minQty} className="text-sm" readOnly />
                      <Input type="number" step="0.1" value={tier.factorLow} className="text-sm"
                        onChange={(e) => {
                          const ranges = [...(config?.price?.ladder_factor_ranges || [])];
                          ranges[i] = [parseFloat(e.target.value) || 1.0, ranges[i]?.[1] || 1.5];
                          updateConfig("price.ladder_factor_ranges", ranges);
                        }}
                      />
                      <Input type="number" step="0.1" value={tier.factorHigh} className="text-sm"
                        onChange={(e) => {
                          const ranges = [...(config?.price?.ladder_factor_ranges || [])];
                          ranges[i] = [ranges[i]?.[0] || 1.0, parseFloat(e.target.value) || 1.5];
                          updateConfig("price.ladder_factor_ranges", ranges);
                        }}
                      />
                      <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive"
                        onClick={() => {
                          const orders = [...(config?.price?.ladder_min_orders || [])];
                          const ranges = [...(config?.price?.ladder_factor_ranges || [])];
                          orders.splice(i, 1);
                          ranges.splice(i, 1);
                          updateConfig("price.ladder_min_orders", orders);
                          updateConfig("price.ladder_factor_ranges", ranges);
                        }}
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  ))}
                </div>
                <div className="mt-4 p-3 bg-amber-50 rounded-lg border border-amber-100">
                  <p className="text-xs text-amber-700">
                    提示：实际价格 = 出厂价 / 汇率 * 倍率。倍率在下限和上限之间随机选取。
                  </p>
                </div>
                <Separator />
                <div className="space-y-3">
                  <p className="text-sm font-medium">售卖单位（阶梯价之前填写）</p>
                  <div className="grid grid-cols-4 gap-4 items-center">
                    <Label className="text-sm text-right text-muted-foreground">基础销售方式</Label>
                    <select
                      className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                      value={config?.price?.sale_type || "按件卖"}
                      onChange={(e) => updateConfig("price.sale_type", e.target.value)}
                    >
                      <option value="按件卖">按件卖</option>
                      <option value="按批卖">按批卖</option>
                    </select>
                    <Label className="text-sm text-right text-muted-foreground">计量单位</Label>
                    <PriceUnitSelect
                      value={priceUnitDraft}
                      onChange={(v) => {
                        markLocalEdit();
                        setPriceUnitDraft(v);
                        updateConfig("price.price_unit", v);
                      }}
                      className="text-sm"
                    />
                  </div>
                  <p className="text-xs text-muted-foreground px-2">
                    计量单位只能从平台列表中选择，支持搜索匹配（如 Set、Piece）。
                  </p>
                </div>
                <Separator />
                <div className="space-y-3">
                  <div className="flex items-center justify-between px-2">
                    <p className="text-sm font-medium">发货期（可售数量之后填写，最多 {MAX_DELIVERY_TIERS} 档）</p>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="gap-1 h-8"
                      disabled={deliveryTierDrafts.length >= MAX_DELIVERY_TIERS}
                      onClick={() => {
                        markLocalEdit();
                        setDeliveryTierDrafts((prev) => {
                          if (prev.length >= MAX_DELIVERY_TIERS) return prev;
                          return [...prev, { max_order: "", delivery_days: "" }];
                        });
                      }}
                    >
                      <Plus className="w-3.5 h-3.5" />
                      增加一档
                    </Button>
                  </div>
                  <div className="grid grid-cols-[1fr_1fr_1.5fr_72px] gap-4 text-xs font-medium text-muted-foreground px-2">
                    <span>数量上限 (≤)</span>
                    <span>发货天数</span>
                    <span>说明</span>
                    <span className="text-right">操作</span>
                  </div>
                  {deliveryTierDrafts.map((tier, i) => (
                    <div key={i} className="grid grid-cols-[1fr_1fr_1.5fr_72px] gap-4 items-center">
                      <Input
                        type="text"
                        inputMode="numeric"
                        value={tier.max_order}
                        placeholder="0 表示以上"
                        className="text-sm"
                        onChange={(e) => {
                          markLocalEdit();
                          const v = e.target.value.replace(/[^\d]/g, "");
                          setDeliveryTierDrafts((prev) => {
                            const next = prev.map((row, idx) =>
                              idx === i ? { ...row, max_order: v } : row,
                            );
                            return next;
                          });
                        }}
                        onBlur={() => {
                          setDeliveryTierDrafts((prev) => {
                            updateConfig("delivery.ladder_delivery", draftsToDeliveryTiers(prev));
                            return prev;
                          });
                        }}
                      />
                      <Input
                        type="text"
                        inputMode="numeric"
                        value={tier.delivery_days}
                        placeholder="天数"
                        className="text-sm"
                        onChange={(e) => {
                          markLocalEdit();
                          const v = e.target.value.replace(/[^\d]/g, "");
                          setDeliveryTierDrafts((prev) =>
                            prev.map((row, idx) => (idx === i ? { ...row, delivery_days: v } : row)),
                          );
                        }}
                        onBlur={() => {
                          setDeliveryTierDrafts((prev) => {
                            updateConfig("delivery.ladder_delivery", draftsToDeliveryTiers(prev));
                            return prev;
                          });
                        }}
                      />
                      <span className="text-xs text-muted-foreground">
                        {deliveryTierLabel(i, deliveryTierDrafts.length)}
                      </span>
                      <div className="flex justify-end">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive h-8 w-8 p-0"
                          disabled={deliveryTierDrafts.length <= 1}
                          onClick={() => {
                            markLocalEdit();
                            setDeliveryTierDrafts((prev) => {
                              if (prev.length <= 1) return prev;
                              const next = prev.filter((_, idx) => idx !== i);
                              updateConfig("delivery.ladder_delivery", draftsToDeliveryTiers(next));
                              return next;
                            });
                          }}
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      </div>
                    </div>
                  ))}
                  <p className="text-xs text-muted-foreground px-2">
                    可自由增减档位（1～{MAX_DELIVERY_TIERS} 档）；页面已有发货期时将自动跳过。
                  </p>
                </div>
                <Separator />
                <div className="space-y-3">
                  <p className="text-sm font-medium">SKU 库存与商品编码</p>
                  <div className="grid grid-cols-4 gap-4 items-center">
                    <Label className="text-sm text-right text-muted-foreground">可售数量</Label>
                    <Input
                      type="number"
                      min={0}
                      max={999999999}
                      value={config?.price?.product_inventory ?? 99999}
                      onChange={(e) =>
                        updateConfig("price.product_inventory", parseInt(e.target.value, 10) || 0)
                      }
                      className="text-sm"
                    />
                    <Label className="text-sm text-right text-muted-foreground">商品编码</Label>
                    <Input
                      value={config?.price?.sku_outer_id ?? ""}
                      maxLength={64}
                      placeholder="填入每个 SKU 的商品编码（含美国 HS 编码维护）"
                      onChange={(e) => updateConfig("price.sku_outer_id", e.target.value)}
                      className="text-sm"
                    />
                  </div>
                  <p className="text-xs text-muted-foreground px-2">
                    发品时在阶梯价设置后自动填入各 SKU 的可售数量与商品编码；美国 HS 编码维护与商品编码为同一填写位置。
                  </p>
                </div>
                <Separator />
                <div className="space-y-3">
                  <p className="text-sm font-medium">样品服务配置</p>
                  <div className="grid grid-cols-4 gap-4 items-center">
                    <Label className="text-sm text-right text-muted-foreground">样品服务</Label>
                    <Switch
                      checked={config?.price?.sample_service_enabled ?? true}
                      onCheckedChange={(v) => updateConfig("price.sample_service_enabled", v)}
                    />
                    <Label className="text-sm text-right text-muted-foreground">支持轻定制</Label>
                    <Switch
                      checked={config?.price?.sample_support_light_customization ?? false}
                      onCheckedChange={(v) => updateConfig("price.sample_support_light_customization", v)}
                    />
                  </div>
                  <div className="grid grid-cols-4 gap-4 items-center">
                    <Label className="text-sm text-right text-muted-foreground">单次最多索样数量</Label>
                    <Input
                      type="number"
                      min={1}
                      value={config?.price?.sample_max_quantity ?? 1}
                      onChange={(e) => updateConfig("price.sample_max_quantity", parseInt(e.target.value, 10) || 1)}
                      className="text-sm"
                    />
                    <Label className="text-sm text-right text-muted-foreground">样品SKU价格 (USD)</Label>
                    <Input
                      type="number"
                      min={0}
                      step="0.01"
                      placeholder="留空则按阶梯最高价"
                      value={
                        config?.price?.sample_sku_price_usd != null &&
                        Number(config.price.sample_sku_price_usd) > 0
                          ? config.price.sample_sku_price_usd
                          : ""
                      }
                      onChange={(e) => {
                        const raw = e.target.value;
                        if (raw === "") {
                          updateConfig("price.sample_sku_price_usd", null);
                          return;
                        }
                        const n = parseFloat(raw);
                        if (!Number.isNaN(n) && n >= 0) {
                          updateConfig("price.sample_sku_price_usd", n);
                        }
                      }}
                      className="text-sm"
                    />
                  </div>
                  <p className="text-xs text-muted-foreground px-2">
                    发品时在阶梯价设置后自动填入样品服务；样品价留空时使用本档阶梯最高价。
                  </p>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Attribute Config */}
          <TabsContent value="attrs">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">属性配置</CardTitle>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{attributes.length} 个属性</Badge>
                    <Button size="sm" variant="outline" className="gap-1" onClick={handleFetchAttributes} disabled={fetchingAttrs}>
                      <RefreshCw className={`w-3.5 h-3.5 ${fetchingAttrs ? "animate-spin" : ""}`} />
                      {fetchingAttrs ? "获取中..." : "获取属性"}
                    </Button>
                    <Button size="sm" className="gap-1" onClick={openAddAttrForm}>
                      <Plus className="w-3.5 h-3.5" />
                      新增属性
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  <div className="overflow-x-auto rounded-lg border border-border/50 px-2 py-2">
                    <div className="min-w-[980px] space-y-3">
                      <div className="grid grid-cols-[minmax(120px,1.3fr)_minmax(150px,1.6fr)_minmax(110px,0.9fr)_minmax(96px,0.8fr)_minmax(280px,2.2fr)_80px_72px] gap-4 text-xs font-medium text-muted-foreground">
                        <span>属性名</span>
                        <span>容器ID</span>
                        <span>类型</span>
                        <span>填入数量</span>
                        <span>可选值</span>
                        <span>启用</span>
                        <span>操作</span>
                      </div>
                      {attributes.map((attr: any) => (
                        <div key={attr.name} className="grid grid-cols-[minmax(120px,1.3fr)_minmax(150px,1.6fr)_minmax(110px,0.9fr)_minmax(96px,0.8fr)_minmax(280px,2.2fr)_80px_72px] gap-4 items-center">
                          <button
                            type="button"
                            className="text-left text-sm underline-offset-2 hover:underline"
                            onClick={() => openEditAttrForm(attr)}
                            title="点击编辑属性"
                          >
                            {attr.name}
                          </button>
                          <Input value={attr.container_id} className="text-xs font-mono" readOnly />
                          <Badge variant="outline" className="justify-center">{attr.select_type}</Badge>
                          <Input
                            type="number"
                            min={1}
                            value={attrFillCountDrafts[attr.name] ?? String(attr.fill_count || 1)}
                            className="text-xs"
                            onChange={(e) => {
                              setAttrFillCountDrafts((prev) => ({ ...prev, [attr.name]: e.target.value }));
                            }}
                            onBlur={(e) => {
                              updateAttrFillCount(attr.name, e.target.value);
                              const normalized = String(Math.max(1, Number(e.target.value || 1)));
                              setAttrFillCountDrafts((prev) => ({ ...prev, [attr.name]: normalized }));
                            }}
                          />
                          <button
                            type="button"
                            className="text-left text-xs text-muted-foreground truncate hover:text-foreground"
                            onClick={() => openAttrEditor(attr)}
                            title="点击编辑可选值"
                          >
                            {attr.values.join(", ") || "无"}
                          </button>
                          <div className="flex justify-center">
                            <Switch checked={attr.enabled} onCheckedChange={(v) => {
                              const skipAttrs = [...(config?.attributes?.skip_attrs || [])];
                              if (v) {
                                const idx = skipAttrs.indexOf(attr.name);
                                if (idx >= 0) skipAttrs.splice(idx, 1);
                              } else {
                                if (!skipAttrs.includes(attr.name)) skipAttrs.push(attr.name);
                              }
                              updateConfig("attributes.skip_attrs", skipAttrs);
                            }} />
                          </div>
                          <div>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="text-destructive hover:text-destructive"
                              onClick={() => deleteAttr(attr.name)}
                            >
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Cookie Management */}
          <TabsContent value="cookie">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Cookie管理</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <Label className="text-sm">Cookie文件路径</Label>
                  <Input
                    value={config?.paths?.cookie_file || ""}
                    onChange={(e) => updateConfig("paths.cookie_file", e.target.value)}
                    className="text-sm font-mono"
                  />
                </div>
                <Separator />
                <div className="space-y-2">
                  <Label className="text-sm">Cookie状态</Label>
                  <Badge variant="outline" className="gap-1.5 text-emerald-600 border-emerald-200 bg-emerald-50">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                    请通过后端管理Cookie
                  </Badge>
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Payment Config */}
          {isAdminSession ? (
          <TabsContent value="payment">
            <Card>
              <CardHeader>
                <CardTitle className="text-base">支付配置</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">严格网关模式</Label>
                  <div className="col-span-3">
                    <Switch
                      checked={!!config?.payment?.strict_gateway_mode}
                      onCheckedChange={(v) => updateConfig("payment.strict_gateway_mode", v)}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">生产网关模式</Label>
                  <div className="col-span-3">
                    <Switch
                      checked={!!config?.payment?.production_gateway_mode}
                      onCheckedChange={(v) => updateConfig("payment.production_gateway_mode", v)}
                    />
                  </div>
                </div>

                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">微信支付启用</Label>
                  <div className="col-span-3">
                    <Switch
                      checked={!!config?.payment?.wechat_enabled}
                      onCheckedChange={(v) => updateConfig("payment.wechat_enabled", v)}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">微信商户号</Label>
                  <div className="col-span-3">
                    <Input value={config?.payment?.wechat_mch_id || ""} onChange={(e) => updateConfig("payment.wechat_mch_id", e.target.value)} className="text-sm font-mono" />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">微信AppID</Label>
                  <div className="col-span-3">
                    <Input value={config?.payment?.wechat_app_id || ""} onChange={(e) => updateConfig("payment.wechat_app_id", e.target.value)} className="text-sm font-mono" />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">微信回调密钥</Label>
                  <div className="col-span-3">
                    <Input type="password" value={config?.payment?.wechat_secret || ""} onChange={(e) => updateConfig("payment.wechat_secret", e.target.value)} className="text-sm font-mono" />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">微信APIv3密钥</Label>
                  <div className="col-span-3">
                    <Input type="password" value={config?.payment?.wechat_api_v3_key || ""} onChange={(e) => updateConfig("payment.wechat_api_v3_key", e.target.value)} className="text-sm font-mono" />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">微信证书序列号</Label>
                  <div className="col-span-3">
                    <Input value={config?.payment?.wechat_serial_no || ""} onChange={(e) => updateConfig("payment.wechat_serial_no", e.target.value)} className="text-sm font-mono" />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">微信私钥PEM</Label>
                  <div className="col-span-3">
                    <Textarea value={config?.payment?.wechat_private_key_pem || ""} onChange={(e) => updateConfig("payment.wechat_private_key_pem", e.target.value)} className="text-xs font-mono min-h-[120px]" />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">微信回调IP白名单</Label>
                  <div className="col-span-3">
                    <Input
                      value={Array.isArray(config?.payment?.wechat_callback_allowed_ips) ? config.payment.wechat_callback_allowed_ips.join(",") : ""}
                      onChange={(e) => updateConfig("payment.wechat_callback_allowed_ips", e.target.value.split(",").map((s: string) => s.trim()).filter((s: string) => !!s))}
                      className="text-sm font-mono"
                      placeholder="多个IP用英文逗号分隔"
                    />
                  </div>
                </div>

                <Separator />

                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">支付宝启用</Label>
                  <div className="col-span-3">
                    <Switch
                      checked={!!config?.payment?.alipay_enabled}
                      onCheckedChange={(v) => updateConfig("payment.alipay_enabled", v)}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">支付宝AppID</Label>
                  <div className="col-span-3">
                    <Input value={config?.payment?.alipay_app_id || ""} onChange={(e) => updateConfig("payment.alipay_app_id", e.target.value)} className="text-sm font-mono" />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">支付宝回调密钥</Label>
                  <div className="col-span-3">
                    <Input type="password" value={config?.payment?.alipay_secret || ""} onChange={(e) => updateConfig("payment.alipay_secret", e.target.value)} className="text-sm font-mono" />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">支付宝公钥</Label>
                  <div className="col-span-3">
                    <Textarea value={config?.payment?.alipay_public_key || ""} onChange={(e) => updateConfig("payment.alipay_public_key", e.target.value)} className="text-xs font-mono min-h-[120px]" />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">支付宝私钥</Label>
                  <div className="col-span-3">
                    <Textarea value={config?.payment?.alipay_private_key || ""} onChange={(e) => updateConfig("payment.alipay_private_key", e.target.value)} className="text-xs font-mono min-h-[120px]" />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">支付宝网关地址</Label>
                  <div className="col-span-3">
                    <Input value={config?.payment?.alipay_gateway_url || "https://openapi.alipay.com/gateway.do"} onChange={(e) => updateConfig("payment.alipay_gateway_url", e.target.value)} className="text-sm font-mono" />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">支付宝回调IP白名单</Label>
                  <div className="col-span-3">
                    <Input
                      value={Array.isArray(config?.payment?.alipay_callback_allowed_ips) ? config.payment.alipay_callback_allowed_ips.join(",") : ""}
                      onChange={(e) => updateConfig("payment.alipay_callback_allowed_ips", e.target.value.split(",").map((s: string) => s.trim()).filter((s: string) => !!s))}
                      className="text-sm font-mono"
                      placeholder="多个IP用英文逗号分隔"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">回调时间戳容忍秒数</Label>
                  <div className="col-span-3">
                    <Input
                      type="number"
                      value={config?.payment?.callback_timestamp_tolerance_sec ?? 600}
                      onChange={(e) => updateConfig("payment.callback_timestamp_tolerance_sec", Number(e.target.value || 600))}
                      className="text-sm font-mono"
                    />
                  </div>
                </div>

                <Separator />

                <div className="text-sm font-semibold text-foreground">积分扣费配置</div>
                <div className="text-xs text-muted-foreground -mt-2">
                  调整各功能每次成功执行时扣除的积分（支持小数）。保存后立即生效。
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">产品优化建议（每条）</Label>
                  <div className="col-span-3">
                    <Input
                      type="number"
                      step="0.01"
                      min={0}
                      value={config?.points_pricing?.title_optimize_per_item ?? 0.2}
                      onChange={(e) => updateConfig("points_pricing.title_optimize_per_item", Number(e.target.value || 0))}
                      className="text-sm font-mono"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">流量分析（每次）</Label>
                  <div className="col-span-3">
                    <Input
                      type="number"
                      step="0.01"
                      min={0}
                      value={config?.points_pricing?.traffic_ai_per_run ?? 0.5}
                      onChange={(e) => updateConfig("points_pricing.traffic_ai_per_run", Number(e.target.value || 0))}
                      className="text-sm font-mono"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">AI 生图 1K（每张）</Label>
                  <div className="col-span-3">
                    <Input
                      type="number"
                      step="0.01"
                      min={0}
                      value={config?.points_pricing?.ai_image_1k ?? 0.6}
                      onChange={(e) => updateConfig("points_pricing.ai_image_1k", Number(e.target.value || 0))}
                      className="text-sm font-mono"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">AI 生图 2K（每张）</Label>
                  <div className="col-span-3">
                    <Input
                      type="number"
                      step="0.01"
                      min={0}
                      value={config?.points_pricing?.ai_image_2k ?? 0.7}
                      onChange={(e) => updateConfig("points_pricing.ai_image_2k", Number(e.target.value || 0))}
                      className="text-sm font-mono"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">AI 生图 4K（每张）</Label>
                  <div className="col-span-3">
                    <Input
                      type="number"
                      step="0.01"
                      min={0}
                      value={config?.points_pricing?.ai_image_4k ?? 0.85}
                      onChange={(e) => updateConfig("points_pricing.ai_image_4k", Number(e.target.value || 0))}
                      className="text-sm font-mono"
                    />
                  </div>
                </div>

                <Separator />

                <div className="grid grid-cols-4 gap-4 items-center">
                  <Label className="text-sm text-right text-muted-foreground">管理员API密钥</Label>
                  <div className="col-span-3">
                    <Input type="password" value={config?.payment?.admin_api_key || ""} onChange={(e) => updateConfig("payment.admin_api_key", e.target.value)} className="text-sm font-mono" />
                  </div>
                </div>

                <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-1">
                  提示：保存后生效。回调接口会校验 sign/signature 与上述密钥一致才会入账。
                </div>
              </CardContent>
            </Card>
          </TabsContent>
          ) : null}
        </Tabs>
      )}

      <Dialog open={attrEditorOpen} onOpenChange={setAttrEditorOpen}>
        <DialogContent className="sm:max-w-[720px] h-[560px] max-h-[560px] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle>编辑可选值：{editingAttrName}</DialogTitle>
          </DialogHeader>

          <div className="space-y-2 flex-1 min-h-0 overflow-hidden">
            <Label className="text-xs text-muted-foreground">每行一个可选值</Label>
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" size="sm" onClick={convertCommaToLines}>逗号转多行</Button>
              <Button type="button" variant="outline" size="sm" onClick={dedupeAndCleanLines}>去重 + 去空行</Button>
            </div>
            <div className="h-[380px] overflow-auto rounded border border-border/60 p-2">
              <Textarea
                value={editingAttrText}
                onChange={(e) => setEditingAttrText(e.target.value)}
                className="min-h-[680px] text-xs border-0 shadow-none p-0 focus-visible:ring-0"
                placeholder="请输入可选值，每行一个"
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setAttrEditorOpen(false)}>取消</Button>
            <Button onClick={saveAttrEditor}>保存可选值</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={attrFormOpen} onOpenChange={setAttrFormOpen}>
        <DialogContent className="sm:max-w-[760px] h-[620px] max-h-[620px] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle>{isAttrEditMode ? "编辑属性" : "新增属性"}</DialogTitle>
          </DialogHeader>

          <div className="flex-1 min-h-0 overflow-auto pr-1 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="text-sm">属性名</Label>
                <Input
                  value={attrForm.name}
                  onChange={(e) => setAttrForm((p) => ({ ...p, name: e.target.value }))}
                  placeholder="例如：材质"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-sm">容器ID</Label>
                <Input
                  value={attrForm.container_id}
                  onChange={(e) => setAttrForm((p) => ({ ...p, container_id: e.target.value }))}
                  placeholder="例如：struct-p-123456"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-sm">类型</Label>
                <Input
                  value={attrForm.select_type}
                  onChange={(e) => setAttrForm((p) => ({ ...p, select_type: e.target.value }))}
                  placeholder="例如：tag / single_search / input"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-sm">填入数量</Label>
                <Input
                  type="number"
                  min={1}
                  value={attrForm.fill_count}
                  onChange={(e) => setAttrForm((p) => ({ ...p, fill_count: e.target.value }))}
                  onBlur={(e) => {
                    const normalized = String(Math.max(1, Number(e.target.value || 1)));
                    setAttrForm((p) => ({ ...p, fill_count: normalized }));
                  }}
                  placeholder="例如：1"
                />
              </div>
              <div className="space-y-2 flex items-end">
                <div className="flex items-center gap-2">
                  <Switch
                    checked={attrForm.enabled}
                    onCheckedChange={(v) => setAttrForm((p) => ({ ...p, enabled: v }))}
                  />
                  <Label className="text-sm">启用该属性</Label>
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <Label className="text-sm">可选值（每行一个）</Label>
              <Textarea
                value={attrForm.valuesText}
                onChange={(e) => setAttrForm((p) => ({ ...p, valuesText: e.target.value }))}
                className="min-h-[320px] text-xs"
                placeholder="请输入可选值，每行一个"
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setAttrFormOpen(false)}>取消</Button>
            <Button onClick={saveAttrForm}>{isAttrEditMode ? "保存修改" : "新增属性"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={specFormOpen} onOpenChange={setSpecFormOpen}>
        <DialogContent className="sm:max-w-[760px] h-[620px] max-h-[620px] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle>{isSpecEditMode ? "编辑规格" : "新增规格"}</DialogTitle>
          </DialogHeader>

          <div className="flex-1 min-h-0 overflow-auto pr-1 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="text-sm">组别</Label>
                <Input
                  value={specForm.group}
                  onChange={(e) => setSpecForm((p) => ({ ...p, group: e.target.value }))}
                  placeholder="请选择或输入组别"
                  list="spec-group-options"
                />
                <datalist id="spec-group-options">
                  {Object.keys(config?.group_urls?.group_url_map || {}).map((g) => (
                    <option key={g} value={g} />
                  ))}
                </datalist>
              </div>
              <div className="space-y-2">
                <Label className="text-sm">规格名</Label>
                <Input
                  value={specForm.name}
                  onChange={(e) => setSpecForm((p) => ({ ...p, name: e.target.value }))}
                  placeholder="例如：材质"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-sm">容器ID</Label>
                <Input
                  value={specForm.container_id}
                  onChange={(e) => setSpecForm((p) => ({ ...p, container_id: e.target.value }))}
                  placeholder="例如：p-191284014"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-sm">填入数量</Label>
                <Input
                  type="number"
                  min={1}
                  value={specForm.max_select}
                  onChange={(e) => setSpecForm((p) => ({ ...p, max_select: Number(e.target.value || 1) }))}
                  placeholder="例如：2"
                />
              </div>
              <div className="space-y-2">
                <Label className="text-sm">交互类型</Label>
                <select
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm"
                  value={specForm.interaction}
                  onChange={(e) => {
                    const v = e.target.value;
                    setSpecForm((p) => ({
                      ...p,
                      interaction: v,
                      type: v === "value_rows" ? "value_rows" : "checkbox",
                      image_subdir:
                        v === "value_rows"
                          ? (p.name === "样式" ? "样式" : "SKU")
                          : p.image_subdir,
                    }));
                  }}
                >
                  <option value="checkbox_grid">复选框网格（如戒指尺寸）</option>
                  <option value="value_rows">输入行 + 规格图（如颜色/样式）</option>
                </select>
              </div>
              <div className="flex items-center gap-3 rounded-md border border-border/60 p-3 md:col-span-2">
                <Switch
                  checked={specForm.enable_sale_attribute}
                  onCheckedChange={(v) => setSpecForm((p) => ({ ...p, enable_sale_attribute: v }))}
                />
                <div className="text-sm">
                  <div>启用顶部规格项</div>
                  <div className="text-xs text-muted-foreground">
                    开启后发品时会勾选发品页顶部「商品规格项」中的「{specForm.name || "该规格"}」；关闭则不勾选、也不填写此规格
                  </div>
                </div>
              </div>
            </div>

            {specForm.interaction === "value_rows" ? (
              <>
                <div className="flex items-center gap-3 rounded-md border border-border/60 p-3">
                  <Switch
                    checked={specForm.enable_spec_image}
                    onCheckedChange={(v) => setSpecForm((p) => ({ ...p, enable_spec_image: v }))}
                  />
                  <div className="text-sm">
                    <div>开启「添加规格图」</div>
                    <div className="text-xs text-muted-foreground">
                      颜色与样式互斥，同时开启时优先颜色；图片路径：主图目录/产品ID/{specForm.image_subdir || "SKU"}/SKU名.后缀
                    </div>
                  </div>
                </div>
                <div className="space-y-2">
                  <Label className="text-sm">规格图子目录（相对主图产品文件夹）</Label>
                  <Input
                    value={specForm.image_subdir}
                    onChange={(e) => setSpecForm((p) => ({ ...p, image_subdir: e.target.value }))}
                    placeholder="SKU"
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-sm">填充颜色/样式（可选，留空则发品时自动读取规格图文件名）</Label>
                  <Textarea
                    value={specForm.defaultValuesText}
                    onChange={(e) => setSpecForm((p) => ({ ...p, defaultValuesText: e.target.value }))}
                    className="min-h-[240px] text-xs"
                    placeholder={"留空：发品时自动扫描 主图目录/产品ID/SKU/ 下图片名\n\n或手动填写以限定顺序：\nGold\nSilver\nRose Gold"}
                  />
                  <p className="text-xs text-muted-foreground">
                    图片路径：主图目录/产品ID/{specForm.image_subdir || "SKU"}/SKU名.后缀；手动填写时须与文件名一致。
                  </p>
                </div>
              </>
            ) : (
              <>
                <div className="space-y-2">
                  <Label className="text-sm">可选值池（每行一个）</Label>
                  <Textarea
                    value={specForm.valuesText}
                    onChange={(e) => setSpecForm((p) => ({ ...p, valuesText: e.target.value }))}
                    className="min-h-[240px] text-xs"
                    placeholder="请输入规格值，每行一个"
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-sm">默认值（每行一个，需在可选值池中）</Label>
                  <Textarea
                    value={specForm.defaultValuesText}
                    onChange={(e) => setSpecForm((p) => ({ ...p, defaultValuesText: e.target.value }))}
                    className="min-h-[140px] text-xs"
                    placeholder="例如：11"
                  />
                </div>
              </>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setSpecFormOpen(false)}>取消</Button>
            <Button onClick={saveSpecForm} disabled={saving}>
              {saving ? "保存中..." : isSpecEditMode ? "保存修改" : "新增规格"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
