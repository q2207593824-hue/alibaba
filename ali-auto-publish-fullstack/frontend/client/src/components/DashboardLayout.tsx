/**
 * DashboardLayout - Enterprise Business Dashboard Layout
 * Design: Deep navy sidebar + light content area, professional SaaS aesthetic
 * Font: DM Sans (headings) + Noto Sans SC (Chinese body)
 */
import { useEffect, useState } from "react";
import { Link, useLocation } from "wouter";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { prefetchRouteResources } from "@/lib/routePrefetch";
import {
  LayoutDashboard,
  Upload,
  Image,
  Download,
  BarChart3,
  Settings,
  ChevronLeft,
  ChevronRight,
  Package,
  Search,
  Store,
  Activity,
  Stethoscope,
  ChevronDown,
  TrendingUp,
  Crown,
  Video,
  Radio,
  Wand2,
  Share2,
  Sparkles,
  ScanSearch,
} from "lucide-react";

interface NavItem {
  label: string;
  icon: React.ElementType;
  href?: string;
  children?: { label: string; href: string; icon: React.ElementType }[];
}

const navItems: NavItem[] = [
  { label: "控制台", icon: LayoutDashboard, href: "/" },
  {
    label: "产品上传",
    icon: Upload,
    children: [
      { label: "自动发品", href: "/product-upload", icon: Package },
      { label: "优化产品", href: "/optimize-product", icon: Wand2 },
      { label: "新品绑定视频", href: "/video-bind", icon: Video },
      { label: "配置管理", href: "/product-config", icon: Settings },
      { label: "发品页扫描", href: "/publish-page-scanner", icon: ScanSearch },
    ],
  },
  {
    label: "图片管理",
    icon: Image,
    children: [
      { label: "图片规范化", href: "/image-manager", icon: Image },
      { label: "AI 生图", href: "/ai-image-gen", icon: Sparkles },
      { label: "店铺图片采集", href: "/store-image-collect", icon: Image },
    ],
  },
  {
    label: "数据下载",
    icon: Download,
    children: [
      { label: "产品参谋数据", href: "/data-download", icon: BarChart3 },
      { label: "产品运营", href: "/product-operate-download", icon: Store },
      { label: "关键词数据", href: "/keyword-download", icon: Search },
      { label: "行业关键词", href: "/industry-keyword", icon: Search },
      { label: "店铺运营数据", href: "/store-data", icon: Store },
      { label: "流量渠道", href: "/traffic-channel-download", icon: Radio },
    ],
  },
  {
    label: "数据分析",
    icon: BarChart3,
    children: [
      { label: "综合分析", href: "/data-analysis", icon: Activity },
      { label: "周数据分析", href: "/product-diagnosis", icon: Stethoscope },
      { label: "P4P分析", href: "/p4p-analysis", icon: Activity },
      { label: "新发链接监控", href: "/new-links-analysis", icon: Activity },
      { label: "产品优化建议", href: "/title-optimize-analysis", icon: Wand2 },
      { label: "单品分析", href: "/single-product-analysis", icon: Stethoscope },
      { label: "单品渠道数据", href: "/single-product-channel", icon: Share2 },
      { label: "流量分析", href: "/traffic-analysis", icon: TrendingUp },
    ],
  },
  { label: "会员中心", icon: Crown, href: "/membership" },
];

function NavTooltipWrapper({
  collapsed,
  label,
  children,
}: {
  collapsed: boolean;
  label: string;
  children: React.ReactNode;
}) {
  if (!collapsed) return <>{children}</>;
  return (
    <Tooltip delayDuration={100}>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side="right" className="text-xs font-medium">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof window === "undefined") return false;
    return window.innerWidth < 1500;
  });
  const [expandedGroups, setExpandedGroups] = useState<string[]>(["产品上传", "数据下载", "数据分析"]);
  const [location] = useLocation();

  useEffect(() => {
    const onResize = () => {
      if (window.innerWidth < 1200) {
        setCollapsed(true);
      }
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const toggleGroup = (label: string) => {
    setExpandedGroups((prev) =>
      prev.includes(label) ? prev.filter((g) => g !== label) : [...prev, label]
    );
  };

  const isActive = (href: string) => location === href;
  const isGroupActive = (item: NavItem) =>
    item.children?.some((child) => location === child.href) ?? false;

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside
        className={cn(
          "flex flex-col h-full transition-all duration-300 ease-in-out relative z-20 shrink-0",
          "bg-sidebar text-sidebar-foreground border-r border-sidebar-border/30",
          collapsed ? "w-[68px]" : "w-[256px]"
        )}
        onClick={() => {
          if (collapsed) setCollapsed(false);
        }}
      >
        {/* Logo Area */}
        <div className="flex items-center h-[60px] px-4 border-b border-sidebar-border/50 shrink-0">
          {!collapsed ? (
            <div className="flex items-center gap-3 overflow-hidden">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-amber-400 to-amber-500 flex items-center justify-center shrink-0 shadow-lg shadow-amber-500/20">
                <span className="text-white font-bold text-sm">Ali</span>
              </div>
              <div className="overflow-hidden">
                <h1 className="text-[13px] font-semibold text-sidebar-foreground truncate tracking-tight">
                  智能运营管理
                </h1>
                <p className="text-[10px] text-sidebar-foreground/40 truncate">
                  Alibaba Operation System
                </p>
              </div>
            </div>
          ) : (
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-amber-400 to-amber-500 flex items-center justify-center mx-auto shadow-lg shadow-amber-500/20">
              <span className="text-white font-bold text-sm">A</span>
            </div>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-3 px-2.5 space-y-0.5">
          {navItems.map((item) => {
            if (item.href) {
              return (
                <NavTooltipWrapper key={item.label} collapsed={collapsed} label={item.label}>
                  <Link href={item.href}>
                    <div
                      onMouseEnter={() => prefetchRouteResources(item.href!)}
                      className={cn(
                        "flex items-center gap-3 px-3 py-2.5 rounded-lg text-[13px] transition-all duration-200 group",
                        collapsed && "justify-center px-0",
                        isActive(item.href)
                          ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-sm"
                          : "text-sidebar-foreground/65 hover:bg-sidebar-accent/40 hover:text-sidebar-foreground"
                      )}
                    >
                      <item.icon
                        className={cn(
                          "w-[18px] h-[18px] shrink-0 transition-colors",
                          isActive(item.href)
                            ? "text-amber-400"
                            : "text-sidebar-foreground/40 group-hover:text-sidebar-foreground/65"
                        )}
                      />
                      {!collapsed && <span className="truncate">{item.label}</span>}
                      {isActive(item.href) && !collapsed && (
                        <div className="ml-auto w-1.5 h-1.5 rounded-full bg-amber-400" />
                      )}
                    </div>
                  </Link>
                </NavTooltipWrapper>
              );
            }

            // Group with children
            const groupActive = isGroupActive(item);
            const isExpanded = expandedGroups.includes(item.label);

            return (
              <div key={item.label}>
                <NavTooltipWrapper collapsed={collapsed} label={item.label}>
                  <button
                    onClick={() => !collapsed && toggleGroup(item.label)}
                    className={cn(
                      "flex items-center gap-3 px-3 py-2.5 rounded-lg text-[13px] w-full transition-all duration-200 group",
                      collapsed && "justify-center px-0",
                      groupActive
                        ? "text-sidebar-foreground"
                        : "text-sidebar-foreground/65 hover:bg-sidebar-accent/40 hover:text-sidebar-foreground"
                    )}
                  >
                    <item.icon
                      className={cn(
                        "w-[18px] h-[18px] shrink-0 transition-colors",
                        groupActive
                          ? "text-amber-400"
                          : "text-sidebar-foreground/40 group-hover:text-sidebar-foreground/65"
                      )}
                    />
                    {!collapsed && (
                      <>
                        <span className="truncate">{item.label}</span>
                        <ChevronDown
                          className={cn(
                            "ml-auto w-3.5 h-3.5 text-sidebar-foreground/30 transition-transform duration-200",
                            isExpanded && "rotate-180"
                          )}
                        />
                      </>
                    )}
                  </button>
                </NavTooltipWrapper>
                {!collapsed && isExpanded && item.children && (
                  <div className="ml-[18px] pl-4 border-l border-sidebar-border/30 mt-0.5 mb-1 space-y-0.5">
                    {item.children.map((child) => (
                      <Link key={child.href} href={child.href}>
                        <div
                          onMouseEnter={() => prefetchRouteResources(child.href)}
                          className={cn(
                            "flex items-center gap-2.5 px-3 py-2 rounded-md text-[12px] transition-all duration-200",
                            isActive(child.href)
                              ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-sm"
                              : "text-sidebar-foreground/50 hover:bg-sidebar-accent/30 hover:text-sidebar-foreground/75"
                          )}
                        >
                          <child.icon
                            className={cn(
                              "w-3.5 h-3.5 shrink-0",
                              isActive(child.href) ? "text-amber-400" : ""
                            )}
                          />
                          <span className="truncate">{child.label}</span>
                        </div>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        {/* Bottom section */}
        <div className="border-t border-sidebar-border/30 p-2.5 shrink-0">
          <NavTooltipWrapper collapsed={collapsed} label={collapsed ? "展开侧栏" : "收起侧栏"}>
            <button
              onClick={() => setCollapsed(!collapsed)}
              className="flex items-center justify-center w-full py-2 rounded-lg text-sidebar-foreground/40 hover:bg-sidebar-accent/40 hover:text-sidebar-foreground/70 transition-all"
            >
              {collapsed ? (
                <ChevronRight className="w-4 h-4" />
              ) : (
                <>
                  <ChevronLeft className="w-4 h-4" />
                  <span className="ml-2 text-[11px]">收起侧栏</span>
                </>
              )}
            </button>
          </NavTooltipWrapper>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto bg-background">
        {children}
      </main>
    </div>
  );
}
