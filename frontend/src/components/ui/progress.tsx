import * as React from "react"

import { cn } from "@/lib/utils"

export function Progress({
  className,
  value = 0,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  value?: number
}) {
  const normalizedValue = Math.max(0, Math.min(100, value))

  return (
    <div className={cn("relative h-2 w-full overflow-hidden rounded-full bg-secondary", className)} {...props}>
      <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${normalizedValue}%` }} />
    </div>
  )
}
