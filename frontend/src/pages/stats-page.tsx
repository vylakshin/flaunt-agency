import { useEffect } from "react"

import { PageShell } from "@/components/app/page-shell"
import { Skeleton } from "@/components/ui/skeleton"
import {
  StatusArchitectureMap,
  StatusBoard,
  StatusBoardHeader,
  StatusFleetPanel,
  StatusGlobalBanner,
  StatusIncidents,
  StatusLayerSection,
} from "@/components/status/status-board"
import { useJsonQuery } from "@/hooks/use-json-query"
import type { StatsPayload } from "@/types/app"

export function StatsPage() {
  const { data, isLoading, error } = useJsonQuery<StatsPayload>("/api/app/stats")

  useEffect(() => {
    if (data) document.title = "Flaunt — Системы"
  }, [data])

  if (isLoading) {
    return (
      <PageShell wide>
        <div className="status-board">
          <Skeleton className="h-14 w-full max-w-md" />
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      </PageShell>
    )
  }

  if (error || !data?.systems_status) {
    return (
      <PageShell wide>
        <div className="status-board">
          <div className="status-section-panel p-4 text-sm text-red-300">{error ?? "Не удалось загрузить карту систем."}</div>
        </div>
      </PageShell>
    )
  }

  const systems = data.systems_status

  return (
    <PageShell wide className="max-w-6xl">
      <StatusBoard>
        <StatusBoardHeader updatedAt={systems.summary.updated_at} />
        <StatusGlobalBanner summary={systems.summary} />
        <StatusArchitectureMap />
        <StatusFleetPanel fleet={systems.fleet} />
        {systems.layers.map((layer) => (
          <StatusLayerSection key={layer.id} layer={layer} />
        ))}
        <StatusIncidents incidents={systems.incidents} />
      </StatusBoard>
    </PageShell>
  )
}
