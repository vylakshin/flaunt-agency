import { AlertTriangle, CheckCircle2, Radio, Server, Trophy, XCircle, type LucideIcon } from "lucide-react"
import type { ReactNode } from "react"

import { BrandLogo } from "@/components/app/brand-logo"
import { cn } from "@/lib/utils"
import type { StatsPayload } from "@/types/app"

export type StatusLevel = StatsPayload["systems_status"]["summary"]["status"]
export type StatusBarState = "up" | "warn" | "down"

type SystemsStatus = StatsPayload["systems_status"]

const layerIcons: Record<string, LucideIcon> = {
  core: Server,
  twitch: Radio,
  integrations: Trophy,
  delivery: CheckCircle2,
}

export function StatusBoard({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("status-board", className)}>{children}</div>
}

export function StatusBoardHeader({ updatedAt }: { updatedAt: string }) {
  return (
    <header className="status-board-header">
      <BrandLogo subtitle="Системы" className="[&_.brand-mark]:rounded-xl" />
      <div>
        <div className="status-board-title font-display">Карта систем Flaunt</div>
        <div className="text-xs text-muted-foreground">Живые метрики процесса, Twitch, продуктов и интеграций · {updatedAt}</div>
      </div>
    </header>
  )
}

export function StatusGlobalBanner({ summary }: { summary: SystemsStatus["summary"] }) {
  const Icon = summary.status === "healthy" ? CheckCircle2 : summary.status === "warning" ? AlertTriangle : XCircle
  const tone =
    summary.status === "healthy" ? "status-banner-ok" : summary.status === "warning" ? "status-banner-warn" : "status-banner-error"

  return (
    <div className={cn("status-banner", tone)}>
      <Icon className="size-5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="font-display text-base font-semibold tracking-tight">{summary.label}</div>
        <div className="text-xs text-muted-foreground">Uptime процесса {summary.uptime_label}</div>
      </div>
    </div>
  )
}

export function StatusArchitectureMap() {
  const nodes = [
    { kicker: "Вход", title: "Twitch", detail: "EventSub · Helix · Chat" },
    { kicker: "Ядро", title: "Runtime", detail: "1 Hz · quiz · timers · autobet" },
    { kicker: "Продукт", title: "Quiz", detail: "overlay + раунды" },
    { kicker: "Продукт", title: "Timers", detail: "автосообщения" },
    { kicker: "Продукт", title: "AutoBet", detail: "GSI + OpenDota" },
    { kicker: "Выход", title: "Кабинет", detail: "панель стримера" },
  ]

  return (
    <div className="status-architecture" aria-label="Схема систем Flaunt">
      {nodes.map((node) => (
        <div key={node.title} className="status-arch-node">
          <span className="status-arch-kicker">{node.kicker}</span>
          <strong>{node.title}</strong>
          <span>{node.detail}</span>
        </div>
      ))}
    </div>
  )
}

export function StatusFleetPanel({ fleet }: { fleet: SystemsStatus["fleet"] }) {
  const items = [
    { label: "Каналов в базе", value: fleet.total_channels },
    { label: "С активным ботом", value: fleet.active_channels },
    { label: "Сейчас в эфире", value: fleet.live_channels },
    { label: "Чат подключён", value: fleet.chat_connected_channels },
  ]

  return (
    <div className="status-fleet">
      {items.map((item) => (
        <div key={item.label} className="status-fleet-item">
          <div className="status-fleet-value">{item.value}</div>
          <div className="status-fleet-label">{item.label}</div>
        </div>
      ))}
    </div>
  )
}

export function StatusLayerSection({ layer }: { layer: SystemsStatus["layers"][number] }) {
  const Icon = layerIcons[layer.id] ?? Server

  return (
    <section className="status-layer">
      <div className="status-layer-head">
        <div className="status-layer-icon">
          <Icon className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="status-layer-title">{layer.title}</h2>
            <StatusPill status={layer.status} label={statusText(layer.status)} />
          </div>
          <p className="status-layer-tagline">{layer.tagline}</p>
        </div>
      </div>

      <div className="status-components">
        {layer.components.map((component) => (
          <StatusComponentCard key={component.id} component={component} />
        ))}
      </div>
    </section>
  )
}

export function StatusComponentCard({
  component,
}: {
  component: SystemsStatus["layers"][number]["components"][number]
}) {
  return (
    <article className="status-component">
      <div className="status-component-head">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="status-component-title">{component.label}</h3>
            <StatusPill status={component.status} label={component.status_label} />
          </div>
          <div className="status-component-role">{component.role}</div>
        </div>
      </div>

      <p className="status-component-detail">{component.detail}</p>

      <div className="status-component-metrics">
        {component.metrics.map((metric) => (
          <div key={`${component.id}-${metric.label}`} className="status-metric">
            <div className="status-metric-label">{metric.label}</div>
            <div className="status-metric-value">{metric.value}</div>
          </div>
        ))}
      </div>

      {component.history.length ? (
        <div className="status-component-history">
          <div className="status-history-caption">Последние {component.history.length} проверок тикера</div>
          <div className="status-bars" aria-hidden>
            {component.history.map((bar, index) => (
              <span key={`${component.id}-bar-${index}`} className={cn("status-bar", historyBarClass(bar))} />
            ))}
          </div>
        </div>
      ) : null}
    </article>
  )
}

export function StatusIncidents({ incidents }: { incidents: SystemsStatus["incidents"] }) {
  if (!incidents.length) return null

  return (
    <section className="status-layer">
      <div className="status-layer-head">
        <div className="status-layer-icon status-layer-icon-warn">
          <AlertTriangle className="size-5" />
        </div>
        <div>
          <h2 className="status-layer-title">Инциденты</h2>
          <p className="status-layer-tagline">Свежие ошибки интеграций и фоновых задач.</p>
        </div>
      </div>
      <div className="status-incidents">
        {incidents.map((item, index) => (
          <div key={`${item.key}-${index}`} className="status-incident">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{item.key}</span>
              <span className="status-incident-age">{item.age_label} назад</span>
            </div>
            <div className="status-incident-message">{item.message}</div>
          </div>
        ))}
      </div>
    </section>
  )
}

function StatusPill({ status, label }: { status: StatusLevel; label: string }) {
  return <span className={cn("status-pill", `status-pill-${status}`)}>{label}</span>
}

function statusText(status: StatusLevel) {
  if (status === "healthy") return "Работает"
  if (status === "warning") return "Контроль"
  return "Сбой"
}

function historyBarClass(bar: StatusBarState) {
  if (bar === "up") return "status-bar-up"
  if (bar === "warn") return "status-bar-warn"
  return "status-bar-down"
}
