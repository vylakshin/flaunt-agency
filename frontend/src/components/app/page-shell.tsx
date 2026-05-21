import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export function PageShell({
  children,
  className,
  wide = false,
}: {
  children: ReactNode
  className?: string
  wide?: boolean
}) {
  return <div className={cn("page-shell", wide && "page-shell-wide", className)}>{children}</div>
}
