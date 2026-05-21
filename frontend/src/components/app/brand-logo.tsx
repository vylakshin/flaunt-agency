import { cn } from "@/lib/utils"

export function BrandLogo({
  compact = false,
  className,
}: {
  compact?: boolean
  className?: string
}) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div
        className={cn(
          "brand-gradient flex shrink-0 items-center justify-center rounded-xl font-display font-bold text-white shadow-lg",
          compact ? "size-10 text-sm" : "size-11 text-base"
        )}
        aria-hidden
      >
        F
      </div>
      {!compact ? (
        <div className="min-w-0">
          <div className="font-display text-sm font-bold tracking-tight">Flaunt</div>
          <div className="truncate text-xs text-muted-foreground">Панель стримера</div>
        </div>
      ) : null}
    </div>
  )
}
