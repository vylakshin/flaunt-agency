import { X } from "lucide-react"

import { cn } from "@/lib/utils"

export type ToastNotice = {
  type: "success" | "error" | "warning"
  title: string
  text?: string
}

export function Toast({ notice, onClose }: { notice: ToastNotice | null; onClose: () => void }) {
  if (!notice) return null

  const tone =
    notice.type === "success"
      ? "border-emerald-500/40 bg-emerald-500/12"
      : notice.type === "warning"
        ? "border-amber-500/40 bg-amber-500/12"
        : "border-destructive/40 bg-destructive/12"

  return (
    <div className="fixed bottom-6 right-6 z-[100] w-[min(24rem,calc(100vw-2rem))]">
      <div className={cn("surface-panel flex gap-3 p-4 shadow-2xl", tone)}>
        <div className="min-w-0 flex-1">
          <div className="font-display font-semibold">{notice.title}</div>
          {notice.text ? <p className="mt-1 text-sm text-muted-foreground">{notice.text}</p> : null}
        </div>
        <button
          type="button"
          className="rounded-lg p-1 text-muted-foreground transition hover:bg-accent hover:text-foreground"
          onClick={onClose}
          aria-label="Закрыть"
        >
          <X className="size-4" />
        </button>
      </div>
    </div>
  )
}
