import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export function PageHeader({
  title,
  description,
  actions,
  className,
}: {
  title: string
  description?: string
  actions?: ReactNode
  className?: string
}) {
  return (
    <header className={cn("flex flex-col gap-4 border-b border-border/50 pb-6 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="space-y-2">
        <div className="h-1 w-12 rounded-full brand-gradient" aria-hidden />
        <h1 className="font-display text-3xl font-bold tracking-tight sm:text-4xl">{title}</h1>
        {description ? <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  )
}
