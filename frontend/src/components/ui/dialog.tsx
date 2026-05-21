import { X } from "lucide-react"
import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export function DialogOverlay({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/55 p-4 backdrop-blur-[2px]"
      role="presentation"
      onMouseDown={onClose}
    >
      <div className="sr-only">Диалог</div>
    </div>
  )
}

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  className,
  size = "md",
}: {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  children: ReactNode
  footer?: ReactNode
  className?: string
  size?: "sm" | "md" | "lg"
}) {
  if (!open) return null

  const sizeClass = size === "sm" ? "max-w-md" : size === "lg" ? "max-w-2xl" : "max-w-lg"

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center p-4"
      role="presentation"
      onMouseDown={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        className={cn("panel w-full text-card-foreground shadow-[var(--flaunt-shadow-lg)]", sizeClass, className)}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-border/60 p-5">
          <div className="min-w-0">
            <h2 id="dialog-title" className="font-display text-lg font-semibold">
              {title}
            </h2>
            {description ? <p className="mt-1 text-sm text-muted-foreground">{description}</p> : null}
          </div>
          <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label="Закрыть">
            <X className="size-4" />
          </Button>
        </div>
        <div className="p-5">{children}</div>
        {footer ? <div className="flex flex-col-reverse gap-2 border-t border-border/60 p-5 sm:flex-row sm:justify-end">{footer}</div> : null}
      </div>
    </div>
  )
}
