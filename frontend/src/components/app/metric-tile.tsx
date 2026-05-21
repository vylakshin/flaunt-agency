import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

/** @deprecated Prefer StatCard */
export function MetricTile({
  label,
  value,
  hint,
  icon: Icon,
  className,
}: {
  label: string
  value: ReactNode
  hint?: string
  icon?: LucideIcon
  className?: string
}) {
  return (
    <div className={cn("metric-tile", className)}>
      <div className="flex items-start justify-between gap-3">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</span>
        {Icon ? (
          <span className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Icon className="size-4" />
          </span>
        ) : null}
      </div>
      <div className="mt-2 font-display text-2xl font-bold tabular-nums">{value}</div>
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  )
}
