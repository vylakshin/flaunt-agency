import { cn } from "@/lib/utils"

export function BrandLogo({
  compact = false,
  className,
  subtitle = "Панель стримера",
}: {
  compact?: boolean
  className?: string
  subtitle?: string
}) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <div
        className={cn(
          "brand-mark flex shrink-0 items-center justify-center rounded-xl font-display font-bold",
          compact ? "size-9 text-sm" : "size-10 text-base"
        )}
        aria-hidden
      >
        F
      </div>
      {!compact ? (
        <div className="min-w-0">
          <div className="font-display text-[15px] font-bold tracking-tight">Flaunt</div>
          <div className="truncate text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground">{subtitle}</div>
        </div>
      ) : null}
    </div>
  )
}
