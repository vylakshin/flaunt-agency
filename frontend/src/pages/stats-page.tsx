import { useEffect, useMemo } from "react"

import { PageShell } from "@/components/app/page-shell"
import { Skeleton } from "@/components/ui/skeleton"
import {
  StatusBoard,
  StatusBoardHeader,
  StatusGlobalBanner,
  StatusSection,
  buildStatusBars,
  operationStatus,
  operationUptime,
  statusToPercent,
  type StatusLevel,
  type StatusMonitor,
} from "@/components/status/status-board"
import { useJsonQuery } from "@/hooks/use-json-query"
import type { StatsPayload } from "@/types/app"

export function StatsPage() {
  const { data, isLoading, error } = useJsonQuery<StatsPayload>("/api/app/stats")

  useEffect(() => {
    if (data) document.title = "Flaunt — Healthcheck"
  }, [data])

  const board = useMemo(() => (data ? buildStatusBoard(data) : null), [data])

  if (isLoading) {
    return (
      <PageShell wide>
        <div className="status-board">
          <Skeleton className="h-14 w-full max-w-md" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      </PageShell>
    )
  }

  if (error || !data || !board) {
    return (
      <PageShell wide>
        <div className="status-board">
          <div className="status-section-panel p-4 text-sm text-red-300">{error ?? "Не удалось загрузить статус сервиса."}</div>
        </div>
      </PageShell>
    )
  }

  return (
    <PageShell wide className="max-w-5xl">
      <StatusBoard>
        <StatusBoardHeader updatedAt={data.service_metrics.updated_at || data.stats_updated_at} />
        <StatusGlobalBanner status={board.globalStatus} label={board.globalLabel} uptimeLabel={data.service_metrics.uptime_label} />
        <StatusSection title="OVERVIEW" monitors={board.overview} />
        <StatusSection title="PIPELINES" monitors={board.pipelines} />
        <StatusSection title="OPERATIONS" monitors={board.operations} />
        <StatusSection title="SERVICES" monitors={board.services} />
        {board.incidents.length ? <StatusSection title="INCIDENTS" monitors={board.incidents} /> : null}
      </StatusBoard>
    </PageShell>
  )
}

function buildStatusBoard(data: StatsPayload) {
  const metrics = data.service_metrics
  const health = normalizeHealth(metrics.health.status)
  const chatFallbacks = Number(metrics.overview_cards.find((item) => item.label.includes("Fallback"))?.value ?? 0)
  const recentErrors = metrics.recent_errors.length

  const overview: StatusMonitor[] = [
    {
      id: "platform",
      label: "Flaunt Platform",
      status: health,
      uptimePercent: weightedOverviewUptime(health, metrics.pipelines.map((item) => normalizeHealth(item.status))),
      bars: buildStatusBars(health),
    },
    {
      id: "runtime",
      label: "Runtime ticker",
      status: normalizeHealth(metrics.pipelines[0]?.status ?? health),
      uptimePercent: statusToPercent(normalizeHealth(metrics.pipelines[0]?.status ?? health)),
      bars: buildStatusBars(normalizeHealth(metrics.pipelines[0]?.status ?? health)),
    },
    {
      id: "twitch",
      label: "Twitch API",
      status: normalizeHealth(metrics.pipelines[1]?.status ?? health),
      uptimePercent: statusToPercent(normalizeHealth(metrics.pipelines[1]?.status ?? health)),
      bars: buildStatusBars(normalizeHealth(metrics.pipelines[1]?.status ?? health)),
    },
    {
      id: "chat",
      label: "Chat delivery",
      status: chatFallbacks > 25 ? "warning" : chatFallbacks > 80 ? "error" : "healthy",
      uptimePercent: chatFallbacks > 80 ? 94.5 : chatFallbacks > 25 ? 98.1 : 99.92,
      bars: buildStatusBars(chatFallbacks > 25 ? "warning" : "healthy"),
    },
  ]

  const pipelines: StatusMonitor[] = metrics.pipelines.map((item) => {
    const status = normalizeHealth(item.status)
    return {
      id: `pipeline-${item.label}`,
      label: item.label,
      status,
      uptimePercent: statusToPercent(status),
      bars: buildStatusBars(status),
    }
  })

  const operations: StatusMonitor[] = metrics.operations.map((item) => {
    const status = operationStatus(item.last_ms, item.count)
    return {
      id: `op-${item.label}`,
      label: item.label,
      status,
      uptimePercent: operationUptime(item.last_ms, item.count),
      bars: buildStatusBars(status),
    }
  })

  const services: StatusMonitor[] = metrics.counters.map((item) => {
    const isFailureCounter = /ошиб|fail|пропуск/i.test(item.label)
    const status: StatusLevel = isFailureCounter && item.value > 0 ? (item.value > 20 ? "error" : "warning") : "healthy"
    return {
      id: `counter-${item.label}`,
      label: item.label,
      status,
      uptimePercent: isFailureCounter && item.value > 0 ? (item.value > 20 ? 93.8 : 98.6) : 100,
      bars: buildStatusBars(status),
    }
  })

  const incidents: StatusMonitor[] = metrics.recent_errors.slice(0, 6).map((item, index) => ({
    id: `err-${item.key}-${index}`,
    label: item.key,
    status: "error" as const,
    uptimePercent: 0,
    bars: buildStatusBars("error"),
    windowLabel: `${item.age_label} назад`,
  }))

  const globalStatus: StatusLevel =
    health === "error" || recentErrors > 8 ? "error" : health === "warning" || recentErrors > 0 ? "warning" : "healthy"

  const globalLabel =
    globalStatus === "healthy"
      ? "All Systems Operational"
      : globalStatus === "warning"
        ? "Degraded Performance"
        : "Service Disruption"

  return { overview, pipelines, operations, services, incidents, globalStatus, globalLabel }
}

function normalizeHealth(status: string): StatusLevel {
  if (status === "healthy" || status === "ok") return "healthy"
  if (status === "warning") return "warning"
  return "error"
}

function weightedOverviewUptime(platform: StatusLevel, pipelineStatuses: StatusLevel[]) {
  const values = [statusToPercent(platform), ...pipelineStatuses.map(statusToPercent)]
  const sum = values.reduce((total, value) => total + value, 0)
  return Math.round((sum / values.length) * 100) / 100
}
