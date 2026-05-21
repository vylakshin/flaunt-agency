import { X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

export type ToastNotice = {
  type: "success" | "error" | "info" | "warning"
  title: string
  text?: string
}

export function Toast({ notice, onClose }: { notice: ToastNotice | null; onClose: () => void }) {
  if (!notice) return null

  const tone =
    notice.type === "success"
      ? "border-[color-mix(in_srgb,var(--health-ok)_35%,var(--flaunt-border))]"
      : notice.type === "error"
        ? "border-[color-mix(in_srgb,var(--health-error)_35%,var(--flaunt-border))]"
        : notice.type === "warning"
          ? "border-[color-mix(in_srgb,var(--health-warn)_35%,var(--flaunt-border))]"
          : ""

  return (
    <div
      className={cn(
        "panel fixed bottom-4 right-4 z-50 flex w-[min(22rem,calc(100vw-2rem))] items-start gap-3 p-4 shadow-[var(--flaunt-shadow-lg)]",
        tone
      )}
      role="status"
    >
      <div className="min-w-0 flex-1">
        <div className="font-semibold">{notice.title}</div>
        {notice.text ? <div className="mt-1 text-sm text-muted-foreground">{notice.text}</div> : null}
      </div>
      <Button type="button" variant="ghost" size="icon" className="size-8 shrink-0" onClick={onClose} aria-label="Закрыть">
        <X className="size-4" />
      </Button>
    </div>
  )
}
