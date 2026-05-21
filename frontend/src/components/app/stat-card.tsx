import type { LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = "default",
  className,
}: {
  label: string
  value: ReactNode
  hint?: string
  icon?: LucideIcon
  tone?: "default" | "success" | "warning" | "error"
  className?: string
}) {
  const toneClass =
    tone === "success"
      ? "border-[color-mix(in_srgb,var(--health-ok)_30%,var(--flaunt-border))]"
      : tone === "warning"
        ? "border-[color-mix(in_srgb,var(--health-warn)_30%,var(--flaunt-border))]"
        : tone === "error"
          ? "border-[color-mix(in_srgb,var(--health-error)_30%,var(--flaunt-border))]"
          : ""

  return (
    <div className={cn("panel-muted flex flex-col gap-3 p-5", toneClass, className)}>
      <div className="flex items-start justify-between gap-3">
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</span>
        {Icon ? (
          <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Icon className="size-4" />
          </span>
        ) : null}
      </div>
      <div className="font-display text-2xl font-bold tabular-nums tracking-tight">{value}</div>
      {hint ? <p className="text-xs leading-relaxed text-muted-foreground">{hint}</p> : null}
    </div>
  )
}
