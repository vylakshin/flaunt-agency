import { CheckCircle2, AlertTriangle, XCircle } from "lucide-react"
import type { ReactNode } from "react"

import { BrandLogo } from "@/components/app/brand-logo"
import { cn } from "@/lib/utils"

export type StatusLevel = "healthy" | "warning" | "error"
export type StatusBarState = "up" | "down" | "pending" | "maintenance"

export type StatusMonitor = {
  id: string
  label: string
  uptimePercent: number
  status: StatusLevel
  bars: StatusBarState[]
  windowLabel?: string
}

export function StatusBoard({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("status-board", className)}>{children}</div>
}

export function StatusBoardHeader({ updatedAt }: { updatedAt: string }) {
  return (
    <header className="status-board-header">
      <BrandLogo subtitle="Healthcheck" className="[&_.brand-mark]:rounded-xl" />
      <div className="status-board-title font-display">FLAUNT — HEALTHCHECK</div>
      <div className="text-xs text-[var(--status-muted)]">Обновлено {updatedAt}</div>
    </header>
  )
}

export function StatusGlobalBanner({
  status,
  label,
  uptimeLabel,
}: {
  status: StatusLevel
  label: string
  uptimeLabel: string
}) {
  const Icon = status === "healthy" ? CheckCircle2 : status === "warning" ? AlertTriangle : XCircle
  const tone = status === "healthy" ? "status-banner-ok" : status === "warning" ? "status-banner-warn" : "status-banner-error"

  return (
    <div className={cn("status-banner", tone)}>
      <Icon className="size-5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="font-display text-base font-semibold tracking-tight">{label}</div>
        <div className="text-xs text-[var(--status-muted)]">Uptime {uptimeLabel}</div>
      </div>
    </div>
  )
}

export function StatusSection({ title, monitors }: { title: string; monitors: StatusMonitor[] }) {
  if (!monitors.length) return null

  return (
    <section className="status-section">
      <h2 className="status-section-title">{title}</h2>
      <div className="status-section-panel">
        {monitors.map((monitor) => (
          <StatusMonitorRow key={monitor.id} monitor={monitor} />
        ))}
      </div>
    </section>
  )
}

export function StatusMonitorRow({ monitor }: { monitor: StatusMonitor }) {
  const badgeClass =
    monitor.status === "healthy"
      ? "status-badge-up"
      : monitor.status === "warning"
        ? "status-badge-warn"
        : "status-badge-down"

  return (
    <div className="status-monitor-row">
      <div className={cn("status-uptime-badge", badgeClass)}>{formatUptime(monitor.uptimePercent)}</div>
      <div className="status-monitor-name">{monitor.label}</div>
      <div className="status-monitor-graph">
        <div className="status-bars" aria-hidden>
          {monitor.bars.map((bar, index) => (
            <span key={`${monitor.id}-${index}`} className={cn("status-bar", `status-bar-${bar}`)} />
          ))}
        </div>
        <div className="status-graph-labels">
          <span>{monitor.windowLabel ?? "45m ago"}</span>
          <span>now</span>
        </div>
      </div>
    </div>
  )
}

export function statusToPercent(status: StatusLevel): number {
  if (status === "healthy") return 99.86
  if (status === "warning") return 98.42
  return 94.12
}

export function buildStatusBars(status: StatusLevel, count = 56): StatusBarState[] {
  const bars: StatusBarState[] = Array.from({ length: count }, () => "up")
  if (status === "warning") {
    for (let index = count - 4; index < count - 1; index += 1) bars[index] = "pending"
    bars[count - 1] = "pending"
  }
  if (status === "error") {
    for (let index = count - 10; index < count - 3; index += 1) bars[index] = "down"
    for (let index = count - 3; index < count; index += 1) bars[index] = "down"
  }
  return bars
}

export function operationStatus(lastMs: number, count: number): StatusLevel {
  if (count <= 0) return "healthy"
  if (lastMs >= 2500) return "error"
  if (lastMs >= 900) return "warning"
  return "healthy"
}

export function operationUptime(lastMs: number, count: number): number {
  if (count <= 0) return 100
  const penalty = Math.min(8, lastMs / 180)
  return Math.max(91, 100 - penalty)
}

export function formatUptime(value: number) {
  return `${value.toFixed(2)}%`
}
