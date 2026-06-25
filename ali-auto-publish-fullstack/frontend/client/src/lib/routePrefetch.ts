import { configApi } from "@/lib/api";

const ROUTE_LOADERS: Record<string, () => Promise<unknown>> = {
  "/product-upload": () => import("@/pages/ProductUpload"),
  "/optimize-product": () => import("@/pages/OptimizeProduct"),
  "/video-bind": () => import("@/pages/VideoBind"),
  "/publish-page-scanner": () => import("@/pages/PublishPageScanner"),
  "/product-config": () => import("@/pages/ProductConfig"),
  "/image-manager": () => import("@/pages/ImageManager"),
  "/ai-image-gen": () => import("@/pages/AiImageGen"),
  "/store-image-collect": () => import("@/pages/StoreImageCollect"),
  "/data-download": () => import("@/pages/DataDownload"),
  "/product-operate-download": () => import("@/pages/ProductOperateDownload"),
  "/keyword-download": () => import("@/pages/KeywordDownload"),
  "/industry-keyword": () => import("@/pages/IndustryKeyword"),
  "/store-data": () => import("@/pages/StoreDataDownload"),
  "/traffic-channel-download": () => import("@/pages/TrafficChannelDownload"),
  "/data-analysis": () => import("@/pages/DataAnalysis"),
  "/product-diagnosis": () => import("@/pages/ProductDiagnosis"),
  "/single-product-analysis": () => import("@/pages/SingleProductAnalysis"),
  "/traffic-analysis": () => import("@/pages/TrafficAnalysis"),
  "/single-product-channel": () => import("@/pages/SingleProductChannelData"),
  "/p4p-analysis": () => import("@/pages/P4PAnalysis"),
  "/new-links-analysis": () => import("@/pages/NewLinksAnalysis"),
  "/title-optimize-analysis": () => import("@/pages/TitleOptimizeAnalysis"),
};

const ROUTE_CONFIG_SECTIONS: Record<string, string[]> = {
  "/product-upload": ["upload", "image_norm", "payment"],
  "/optimize-product": ["upload", "data_analysis"],
  "/product-config": ["paths", "upload", "group_urls", "attributes"],
  "/ai-image-gen": ["ai_image_gen"],
  "/store-image-collect": ["data_download"],
  "/data-download": ["data_download"],
  "/product-operate-download": ["data_download"],
  "/keyword-download": ["keyword_download"],
  "/industry-keyword": ["industry_keyword"],
  "/store-data": ["store_overview"],
  "/traffic-channel-download": ["data_download"],
  "/data-analysis": ["data_analysis", "data_download"],
  "/product-diagnosis": ["data_analysis", "data_download"],
  "/single-product-analysis": ["data_analysis"],
  "/traffic-analysis": ["data_analysis"],
  "/single-product-channel": ["data_analysis", "data_download"],
  "/p4p-analysis": ["data_analysis", "data_download"],
  "/new-links-analysis": ["data_analysis"],
  "/title-optimize-analysis": ["data_analysis"],
};

const prefetchedRoutes = new Set<string>();
const prefetchedConfig = new Set<string>();

export function prefetchRoute(href: string): void {
  if (!href || prefetchedRoutes.has(href)) return;
  const loader = ROUTE_LOADERS[href];
  if (!loader) return;
  prefetchedRoutes.add(href);
  void loader().catch(() => {
    prefetchedRoutes.delete(href);
  });
}

export function prefetchRouteConfig(href: string): void {
  if (!href || prefetchedConfig.has(href)) return;
  const sections = ROUTE_CONFIG_SECTIONS[href];
  if (!sections?.length) return;
  prefetchedConfig.add(href);
  void configApi.getSections(sections).catch(() => {
    prefetchedConfig.delete(href);
  });
}

/** 侧栏悬停：预加载页面 chunk + 常用配置段 */
export function prefetchRouteResources(href: string): void {
  prefetchRoute(href);
  prefetchRouteConfig(href);
}
