import * as React from "react"
import { CheckCircle2, CircleAlert, Info, X } from "lucide-react"
import { cva } from "class-variance-authority"

import { cn } from "@/lib/utils"

export type ToastNotice = {
  type: "success" | "warning" | "error"
  title: string
  text: string
}

type ToastPosition = "top-right" | "bottom-right"

const toastVariants = cva(
  "pointer-events-auto relative grid w-full max-w-sm grid-cols-[auto_minmax(0,1fr)_auto] gap-3 rounded-lg border p-4 text-sm shadow-2xl ring-1 ring-black/10 backdrop-blur-md",
  {
    variants: {
      variant: {
        success: "border-emerald-600/40 bg-emerald-950 text-emerald-50 dark:border-emerald-400/35 dark:bg-emerald-950/95 dark:text-emerald-50",
        warning: "border-amber-600/40 bg-amber-950 text-amber-50 dark:border-amber-400/35 dark:bg-amber-950/95 dark:text-amber-50",
        error: "border-destructive/40 bg-red-950 text-red-50 dark:border-red-400/35 dark:bg-red-950/95 dark:text-red-50",
      },
    },
  }
)

const positionClasses: Record<ToastPosition, string> = {
  "top-right": "right-4 top-4 sm:right-6 sm:top-6",
  "bottom-right": "bottom-4 right-4 sm:bottom-6 sm:right-6",
}

export function Toast({
  duration = 3500,
  notice,
  onClose,
  position = "top-right",
}: {
  duration?: number
  notice: ToastNotice | null
  onClose: () => void
  position?: ToastPosition
}) {
  const onCloseRef = React.useRef(onClose)

  React.useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  React.useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => onCloseRef.current(), duration)
    return () => window.clearTimeout(timer)
  }, [duration, notice])

  if (!notice) return null

  const Icon = notice.type === "success" ? CheckCircle2 : notice.type === "warning" ? Info : CircleAlert

  return (
    <div className={cn("pointer-events-none fixed z-[60]", positionClasses[position])}>
      <div className={toastVariants({ variant: notice.type })} role="status" aria-live="polite">
        <Icon className="mt-0.5 size-5 shrink-0" />
        <div className="min-w-0">
          <div className="font-semibold leading-none">{notice.title}</div>
          <div className="mt-1 text-sm leading-relaxed opacity-90">{notice.text}</div>
        </div>
        <button
          type="button"
          className="rounded-md p-1 opacity-80 transition hover:bg-white/10 hover:opacity-100"
          onClick={onClose}
          aria-label="Закрыть уведомление"
        >
          <X className="size-4" />
        </button>
      </div>
    </div>
  )
}
