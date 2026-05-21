import { Activity, AlertTriangle, Bot, Clock3, MessageSquareText, Radio, Server, Sparkles, TimerReset } from "lucide-react"
import { useEffect, type ReactNode } from "react"

import { PageHeader } from "@/components/app/page-header"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useJsonQuery } from "@/hooks/use-json-query"
import type { StatsPayload } from "@/types/app"

export function StatsPage() {
  const { data, isLoading, error } = useJsonQuery<StatsPayload>("/api/app/stats")

  useEffect(() => {
    if (data) document.title = `${data.user.login} — статистика`
  }, [data])

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-16 w-72" />
        <Skeleton className="h-56 w-full" />
      </div>
    )
  }

  if (error || !data) {
    return <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm">{error ?? "Не удалось загрузить статистику."}</div>
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Статистика"
        description={`Обновлено ${data.stats_updated_at}. Здесь собраны продуктовые метрики и состояние самого сервиса.`}
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {data.stats_cards.map((card, index) => {
          const Icon = [MessageSquareText, Clock3, Radio, Activity][index] ?? Sparkles
          return (
            <Card key={card.label}>
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between gap-3">
                  <CardDescription>{card.label}</CardDescription>
                  <div className="flex size-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Icon className="size-5" />
                  </div>
                </div>
                <CardTitle className="text-3xl">{card.value}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">{card.description}</p>
              </CardContent>
            </Card>
          )
        })}
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Server className="size-5" />
                Сервис
              </CardTitle>
              <CardDescription>Внутренние метрики приложения, внешних API и фоновых тиков.</CardDescription>
            </div>
            <Badge variant={metricsBadgeVariant(data.service_metrics.health.status)}>{data.service_metrics.health.label}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {data.service_metrics.overview_cards.map((item, index) => {
              const Icon = [TimerReset, MessageSquareText, Bot, AlertTriangle][index] ?? Activity
              return (
                <div key={item.label} className="rounded-lg border bg-background p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-sm text-muted-foreground">{item.label}</div>
                    <div className="flex size-9 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
                      <Icon className="size-4" />
                    </div>
                  </div>
                  <div className="mt-3 text-2xl font-semibold">{item.value}</div>
                  <div className="mt-1 text-sm text-muted-foreground">{item.description}</div>
                </div>
              )
            })}
          </div>

          <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
            <div className="space-y-3">
              <div className="text-sm font-medium">Контуры</div>
              <div className="divide-y rounded-lg border bg-background">
                {data.service_metrics.pipelines.map((item) => (
                  <div key={item.label} className="flex items-start justify-between gap-3 p-4">
                    <div className="min-w-0">
                      <div className="font-medium">{item.label}</div>
                      <div className="mt-1 text-sm text-muted-foreground">{item.detail}</div>
                    </div>
                    <Badge variant={metricsBadgeVariant(item.status)}>{item.status_label}</Badge>
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-3">
              <div className="text-sm font-medium">Операции</div>
              <div className="divide-y rounded-lg border bg-background">
                {data.service_metrics.operations.map((item) => (
                  <div key={item.label} className="grid gap-2 p-4 sm:grid-cols-[1.2fr_repeat(4,minmax(0,1fr))]">
                    <div className="font-medium">{item.label}</div>
                    <StatValue label="Среднее" value={`${item.avg_ms.toFixed(1)} ms`} />
                    <StatValue label="Последнее" value={`${item.last_ms.toFixed(1)} ms`} />
                    <StatValue label="Пик" value={`${item.max_ms.toFixed(1)} ms`} />
                    <StatValue label="Запусков" value={String(item.count)} />
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="grid gap-6 xl:grid-cols-[0.75fr_1.25fr]">
            <div className="space-y-3">
              <div className="text-sm font-medium">Счётчики</div>
              <div className="divide-y rounded-lg border bg-background">
                {data.service_metrics.counters.map((item) => (
                  <div key={item.label} className="flex items-center justify-between gap-3 p-4">
                    <span className="text-sm text-muted-foreground">{item.label}</span>
                    <span className="font-semibold">{item.value}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="space-y-3">
              <div className="text-sm font-medium">Свежие ошибки</div>
              <div className="divide-y rounded-lg border bg-background">
                {data.service_metrics.recent_errors.length ? (
                  data.service_metrics.recent_errors.map((item) => (
                    <div key={`${item.key}-${item.age_label}-${item.message}`} className="p-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">{item.key}</span>
                        <Badge variant="outline">{item.age_label} назад</Badge>
                      </div>
                      <div className="mt-2 text-sm text-muted-foreground">{item.message}</div>
                    </div>
                  ))
                ) : (
                  <div className="p-4 text-sm text-muted-foreground">Свежих ошибок нет.</div>
                )}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[0.85fr_1.15fr]">
        <Card>
          <CardHeader>
            <CardTitle>Срез по функциям</CardTitle>
            <CardDescription>Что реально используют каналы в текущей панели.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 sm:grid-cols-2 xl:grid-cols-1">
            {data.stats_highlights.map((item) => (
              <div key={item.label} className="flex items-center justify-between rounded-lg border bg-background p-3">
                <span className="text-sm text-muted-foreground">{item.label}</span>
                <span className="font-semibold">{item.value}</span>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Каналы</CardTitle>
            <CardDescription>Статус бота и использование функций по каждому каналу.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {data.recent_channels.map((channel) => (
              <div key={`${channel.login}-${channel.connected_at}`} className="rounded-lg border bg-background p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="truncate font-medium">{channel.display_name}</div>
                      <Badge variant={channel.is_live ? "success" : "outline"}>{channel.is_live ? "В эфире" : "Оффлайн"}</Badge>
                    </div>
                    <div className="text-sm text-muted-foreground">twitch.tv/{channel.login}</div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant={channel.chat_connected ? "success" : "destructive"}>
                      {channel.chat_connected ? "Чат активен" : "Чат не активен"}
                    </Badge>
                    {channel.uses_custom_config ? <Badge variant="outline">свой конфиг</Badge> : null}
                  </div>
                </div>

                <div className="mt-4 grid gap-2 text-sm sm:grid-cols-2 xl:grid-cols-4">
                  <MetricPill icon={<MessageSquareText className="size-4" />} label="Команды" value={`${channel.enabled_custom_command_count}/${channel.custom_command_count}`} />
                  <MetricPill icon={<Clock3 className="size-4" />} label="Таймеры" value={`${channel.enabled_timer_count}/${channel.timer_count}`} />
                  <MetricPill icon={<Sparkles className="size-4" />} label="Aliases/keywords" value={`${channel.command_alias_count}/${channel.command_keyword_count}`} />
                  <MetricPill icon={<Bot className="size-4" />} label="Логи" value={String(channel.action_log_count)} />
                </div>

                <div className="mt-3 text-xs text-muted-foreground">Подключён: {channel.connected_at} · Обновлён: {channel.updated_at}</div>

                {channel.stream_title ? (
                  <div className="mt-3 rounded-md bg-muted/50 p-3 text-sm">
                    <div className="font-medium">{channel.stream_title}</div>
                    <div className="text-muted-foreground">
                      {channel.stream_category || "Без категории"} · {channel.viewer_count} зрителей
                    </div>
                  </div>
                ) : null}
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function MetricPill({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2">
      <span className="flex min-w-0 items-center gap-2 text-muted-foreground">
        {icon}
        <span className="truncate">{label}</span>
      </span>
      <span className="font-semibold">{value}</span>
    </div>
  )
}

function StatValue({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-medium">{value}</div>
    </div>
  )
}

function metricsBadgeVariant(status: "healthy" | "warning" | "error"): "success" | "outline" | "destructive" {
  if (status === "healthy") return "success"
  if (status === "error") return "destructive"
  return "outline"
}
