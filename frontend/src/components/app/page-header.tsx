import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
  className,
}: {
  title: string
  description?: string
  actions?: ReactNode
  eyebrow?: string
  className?: string
}) {
  return (
    <header
      className={cn(
        "flex flex-col gap-5 border-b border-border/60 pb-7 lg:flex-row lg:items-end lg:justify-between",
        className
      )}
    >
      <div className="space-y-3">
        {eyebrow ? (
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-primary">{eyebrow}</p>
        ) : (
          <div className="h-0.5 w-14 rounded-full brand-mark" aria-hidden />
        )}
        <h1 className="font-display text-3xl font-bold tracking-tight sm:text-4xl lg:text-[2.5rem]">{title}</h1>
        {description ? <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground sm:text-base">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  )
}
