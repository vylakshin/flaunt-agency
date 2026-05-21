import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export function MetricTile({
  label,
  value,
  hint,
  icon: Icon,
  trend,
  className,
}: {
  label: string
  value: ReactNode
  hint?: string
  icon?: LucideIcon
  trend?: ReactNode
  className?: string
}) {
  return (
    <div className={cn("metric-tile", className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{label}</div>
        {Icon ? (
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Icon className="size-4" />
          </div>
        ) : null}
      </div>
      <div className="mt-3 font-display text-3xl font-bold tracking-tight">{value}</div>
      {hint ? <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{hint}</p> : null}
      {trend ? <div className="mt-3">{trend}</div> : null}
    </div>
  )
}
