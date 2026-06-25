import { Spinner } from "@/components/ui/spinner";

export default function PageRouteFallback() {
  return (
    <div className="flex h-full min-h-[240px] w-full items-center justify-center gap-2 text-sm text-muted-foreground">
      <Spinner className="size-5" />
      <span>页面加载中...</span>
    </div>
  );
}
