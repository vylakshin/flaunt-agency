import {
  ArrowRight,
  Bot,
  Check,
  CheckCircle2,
  CircleHelp,
  Copy,
  ExternalLink,
  Gift,
  History,
  Loader2,
  MessageSquareText,
  PlayCircle,
  Radio,
  ShieldCheck,
  SquareDashedMousePointer,
  Timer,
  Trophy,
  Zap,
  type LucideIcon,
} from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"

import { EmptyState } from "@/components/app/empty-state"
import { PageError } from "@/components/app/page-error"
import { PageHeader } from "@/components/app/page-header"
import { PageShell } from "@/components/app/page-shell"
import { StatCard } from "@/components/app/stat-card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { AppDialog } from "@/components/app/app-dialog"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { useJsonQuery } from "@/hooks/use-json-query"
import { showNotice } from "@/lib/notify"
import { requestJson } from "@/lib/api"
import { cn } from "@/lib/utils"
import type { DashboardPayload, MutationResult } from "@/types/app"

const quickLinks = [
  { to: "/quiz", label: "Викторина", description: "Раунды и overlay", icon: CircleHelp },
  { to: "/commands", label: "Команды", description: "Чат-бот", icon: MessageSquareText },
  { to: "/giveaways", label: "Розыгрыши", description: "Колесо и чат", icon: Gift },
  { to: "/autobet", label: "Автоставка", description: "Dota 2 и CS2", icon: Trophy },
  { to: "/timers", label: "Таймеры", description: "Автосообщения", icon: Timer },
] as const

export function DashboardPage() {
  const { data, isLoading, error, refetch } = useJsonQuery<DashboardPayload>("/api/app/dashboard")
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  const [isModeratorDialogOpen, setModeratorDialogOpen] = useState(false)

  useEffect(() => {
    if (data) document.title = `${data.user.display_name || data.user.login} — дашборд`
  }, [data])

  const readiness = useMemo(() => buildReadiness(data), [data])
  const quizLabel = useMemo(() => (data ? formatQuizStatus(data.quiz) : ""), [data])
  const activeConfig = useMemo(() => {
    if (!data) return "—"
    const active = data.configs.find((config) => config.is_active)
    return active?.name ?? "Не выбран"
  }, [data])

  async function withAction(action: string, run: () => Promise<void>) {
    setActionBusy(action)
    try {
      await run()
    } catch (err) {
      showNotice("error", "Действие не выполнено", (err as Error).message)
    } finally {
      setActionBusy(null)
    }
  }

  async function activateChat() {
    await withAction("activate-chat", async () => {
      const result = await requestJson<MutationResult>("/api/app/dashboard/chat/activate", { method: "POST" })
      await refetch()
      setModeratorDialogOpen(true)
      showNotice(
        result.warning ? "warning" : "success",
        result.warning ? "Проверь подключение" : "Бот подключается",
        result.warning || "Бот должен появиться в чате через несколько секунд."
      )
    })
  }

  async function makeBotModerator() {
    await withAction("make-moderator", async () => {
      const result = await requestJson<MutationResult>("/api/app/dashboard/chat/moderator", { method: "POST" })
      await refetch()
      if (result.warning) {
        showNotice("warning", "Проверь модератора", result.warning)
        return
      }
      setModeratorDialogOpen(false)
      showNotice("success", "Бот стал модератором", "Права обновлены, бот готов работать в чате.")
    })
  }

  async function deactivateChat() {
    await withAction("deactivate-chat", async () => {
      const result = await requestJson<MutationResult>("/api/app/dashboard/chat/deactivate", { method: "POST" })
      await refetch()
      setModeratorDialogOpen(false)
      const message = result.warning || "Бот отключён от чата и снят с модераторов."
      showNotice(message.includes("но") ? "warning" : "success", "Бот отключён", message)
    })
  }

  if (error || (!isLoading && !data)) {
    return (
      <PageShell>
        <PageError title="Не удалось загрузить дашборд" message={error ?? "Сервер вернул пустой ответ."} />
      </PageShell>
    )
  }

  if (isLoading || !data) return <DashboardPageSkeleton />

  const modeLabel = data.settings.turbo_mode ? "Турбо" : data.settings.quiz_passive_mode ? "Пассивный" : data.settings.quiet_mode ? "Тихий" : "Обычный"

  return (
    <PageShell>
      <PageHeader
        eyebrow={data.user.display_name || data.user.login}
        title="Дашборд"
        description="Подключи бота, проверь статус канала и переходи к нужному разделу."
        actions={
          <Badge variant={readiness.ready ? "success" : "outline"} className="px-3 py-1">
            {readiness.ready ? "Канал готов" : "Нужна настройка"}
          </Badge>
        }
      />

      <ConnectionHero
        actionBusy={actionBusy}
        botLogin={data.bot_login}
        data={data}
        readiness={readiness}
        onActivate={() => void activateChat()}
        onDeactivate={() => void deactivateChat()}
      />

      {data.status.chat_status_text ? (
        <Alert variant="warning">
          <AlertTitle>Требуется внимание</AlertTitle>
          <AlertDescription>{data.status.chat_status_text}</AlertDescription>
        </Alert>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          icon={Radio}
          label="Чат EventSub"
          value={data.status.chat_connected ? "Подключён" : "Не подключён"}
          tone={data.status.chat_connected ? "success" : "error"}
        />
        <StatCard
          icon={ShieldCheck}
          label="Модератор"
          value={data.status.bot_is_moderator ? "Есть права" : "Нет прав"}
          tone={data.status.bot_is_moderator ? "success" : "warning"}
        />
        <StatCard icon={CircleHelp} label="Викторина" value={quizLabel} tone={data.quiz.is_active ? "success" : "default"} />
        <StatCard icon={Zap} label="Режим" value={modeLabel} hint={`Конфиг: ${activeConfig}`} />
      </div>

      <section className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="font-display text-sm font-semibold uppercase tracking-wide text-muted-foreground">Разделы</h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {quickLinks.map((item) => (
            <QuickLinkCard key={item.to} {...item} />
          ))}
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <ActivityFeed logs={data.action_logs ?? []} />

        <div className="space-y-6">
          <QuizSnapshotCard data={data} quizLabel={quizLabel} />
          <OverlayPanel overlayUrl={data.overlay_url} />
          <BotAccountPanel botLogin={data.bot_login} canManage={data.can_manage_bot_account} tokenConfigured={data.bot_token_configured} />
        </div>
      </div>

      <BotModeratorDialog
        actionBusy={actionBusy}
        botIsModerator={data.status.bot_is_moderator}
        botLogin={data.bot_login}
        isOpen={isModeratorDialogOpen}
        onAddModerator={() => void makeBotModerator()}
        onDeactivate={() => void deactivateChat()}
        onClose={() => setModeratorDialogOpen(false)}
      />
    </PageShell>
  )
}

function ConnectionHero({
  actionBusy,
  botLogin,
  data,
  readiness,
  onActivate,
  onDeactivate,
}: {
  actionBusy: string | null
  botLogin: string
  data: DashboardPayload
  readiness: ReturnType<typeof buildReadiness>
  onActivate: () => void
  onDeactivate: () => void
}) {
  const isConnected = data.status.chat_connected
  const isBusy = actionBusy === "activate-chat" || actionBusy === "deactivate-chat"

  const steps = [
    { label: "Подключение к чату", done: data.status.chat_connected, hint: "EventSub слушает сообщения" },
    { label: "Права модератора", done: data.status.bot_is_moderator, hint: `Аккаунт @${botLogin}` },
    { label: "Готов к работе", done: readiness.ready, hint: "Викторина, команды и таймеры доступны" },
  ]

  return (
    <Card className="overflow-hidden py-0">
      <div className="grid gap-6 p-6 lg:grid-cols-[1fr_auto] lg:items-center">
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-3">
            <span className="flex size-12 items-center justify-center rounded-2xl bg-primary/12 text-primary">
              <Bot className="size-6" />
            </span>
            <div>
              <h2 className="font-display text-xl font-bold tracking-tight">Подключение бота</h2>
              <p className="text-sm text-muted-foreground">Управление чатом канала {data.user.display_name || data.user.login}</p>
            </div>
          </div>

          <ol className="grid gap-2 sm:grid-cols-3">
            {steps.map((step, index) => (
              <li
                key={step.label}
                className={cn(
                  "panel-muted flex gap-3 p-3",
                  step.done && "border-[color-mix(in_srgb,var(--health-ok)_35%,var(--flaunt-border))]"
                )}
              >
                <span
                  className={cn(
                    "flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-bold",
                    step.done ? "bg-[color-mix(in_srgb,var(--health-ok)_18%,transparent)] text-[var(--health-ok)]" : "bg-muted text-muted-foreground"
                  )}
                >
                  {step.done ? <Check className="size-3.5" /> : index + 1}
                </span>
                <div className="min-w-0">
                  <div className="text-sm font-medium">{step.label}</div>
                  <div className="text-xs text-muted-foreground">{step.hint}</div>
                </div>
              </li>
            ))}
          </ol>
        </div>

        <div className="flex w-full flex-col gap-3 lg:w-56">
          <Button
            type="button"
            variant={isConnected ? "outline" : "brand"}
            size="lg"
            className="w-full"
            disabled={isBusy}
            onClick={isConnected ? onDeactivate : onActivate}
          >
            {isBusy ? <Loader2 className="size-4 animate-spin" /> : isConnected ? <Radio className="size-4" /> : <PlayCircle className="size-4" />}
            {isConnected ? "Отключить бота" : "Подключить бота"}
          </Button>
          {!isConnected ? (
            <p className="text-center text-xs text-muted-foreground">После подключения выдай боту модератора</p>
          ) : null}
        </div>
      </div>
    </Card>
  )
}

function QuickLinkCard({
  to,
  label,
  description,
  icon: Icon,
}: {
  to: string
  label: string
  description: string
  icon: LucideIcon
}) {
  return (
    <Link
      to={to}
      className="panel-muted group flex flex-col gap-3 p-4 transition hover:border-primary/30 hover:bg-accent/40"
    >
      <span className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary transition group-hover:bg-primary/15">
        <Icon className="size-4" />
      </span>
      <div>
        <div className="font-medium">{label}</div>
        <div className="text-xs text-muted-foreground">{description}</div>
      </div>
      <ArrowRight className="size-4 text-muted-foreground transition group-hover:translate-x-0.5 group-hover:text-primary" />
    </Link>
  )
}

function QuizSnapshotCard({ data, quizLabel }: { data: DashboardPayload; quizLabel: string }) {
  return (
    <section className="panel p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-display font-semibold">Викторина сейчас</h3>
          <p className="mt-1 text-sm text-muted-foreground">{quizLabel}</p>
        </div>
        <Badge variant={data.quiz.is_active ? "success" : "outline"}>{data.quiz.is_active ? "В эфире" : "Пауза"}</Badge>
      </div>

      {data.quiz.is_active || data.quiz.category ? (
        <dl className="mt-4 grid gap-2 text-sm">
          <div className="flex justify-between gap-3 border-b border-border/50 pb-2">
            <dt className="text-muted-foreground">Категория</dt>
            <dd className="font-medium">{data.quiz.category || "—"}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-muted-foreground">Подсказка</dt>
            <dd className="max-w-[12rem] truncate font-medium">{data.quiz.hint || "—"}</dd>
          </div>
        </dl>
      ) : (
        <p className="mt-4 text-sm text-muted-foreground">Раунд не запущен. Настрой конфиг и стартуй игру в разделе викторины.</p>
      )}

      <Button asChild variant="secondary" className="mt-4 w-full">
        <Link to="/quiz">
          Открыть викторину
          <ArrowRight className="size-4" />
        </Link>
      </Button>
    </section>
  )
}

function OverlayPanel({ overlayUrl }: { overlayUrl: string }) {
  const [copied, setCopied] = useState(false)

  async function copyUrl() {
    await navigator.clipboard?.writeText(overlayUrl)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 2000)
  }

  return (
    <section className="panel p-5">
      <div className="flex items-center gap-2">
        <SquareDashedMousePointer className="size-4 text-primary" />
        <h3 className="font-display font-semibold">Overlay для OBS</h3>
      </div>
      <p className="mt-2 text-sm text-muted-foreground">Browser Source — вставь ссылку в OBS для викторины на стриме.</p>
      <div className="relative mt-4">
        <Input className="h-10 pr-20 font-mono text-xs" readOnly value={copied ? "Скопировано" : overlayUrl} />
        <div className="absolute right-1 top-1/2 flex -translate-y-1/2 gap-0.5">
          <Button type="button" variant="ghost" size="icon" className="size-8" onClick={() => void copyUrl()} aria-label="Копировать">
            <Copy className="size-3.5" />
          </Button>
          <Button type="button" variant="ghost" size="icon" className="size-8" onClick={() => window.open(overlayUrl, "_blank")} aria-label="Открыть">
            <ExternalLink className="size-3.5" />
          </Button>
        </div>
      </div>
    </section>
  )
}

function BotAccountPanel({
  botLogin,
  canManage,
  tokenConfigured,
}: {
  botLogin: string
  canManage: boolean
  tokenConfigured: boolean
}) {
  return (
    <section className="panel-muted p-5 text-sm">
      <div className="font-medium">Аккаунт бота</div>
      <div className="mt-2 space-y-1.5 text-muted-foreground">
        <div className="flex justify-between gap-2">
          <span>Логин</span>
          <span className="font-mono text-foreground">@{botLogin}</span>
        </div>
        <div className="flex justify-between gap-2">
          <span>Токен</span>
          <span className={tokenConfigured ? "text-[var(--health-ok)]" : "text-[var(--health-warn)]"}>
            {tokenConfigured ? "Настроен" : "Не настроен"}
          </span>
        </div>
        {canManage ? (
          <p className="pt-2 text-xs">Ты можешь управлять аккаунтом бота из админки.</p>
        ) : null}
      </div>
    </section>
  )
}

function ActivityFeed({ logs }: { logs: DashboardPayload["action_logs"] }) {
  return (
    <section className="panel flex min-h-[28rem] flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-border/60 px-5 py-4">
        <div className="flex items-center gap-2">
          <History className="size-4 text-primary" />
          <h3 className="font-display font-semibold">Лента действий</h3>
        </div>
        <Badge variant="outline">{logs.length}</Badge>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {logs.length ? (
          <ul className="space-y-2">
            {logs.map((item) => {
              const Icon = actionIcon(item.action)
              return (
                <li key={item.id} className="panel-muted flex gap-3 p-3">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Icon className="size-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="font-medium">{item.title}</span>
                      <time className="shrink-0 text-xs text-muted-foreground">{item.created_at_formatted}</time>
                    </div>
                    {item.detail ? <p className="mt-1 text-sm text-muted-foreground">{item.detail}</p> : null}
                    {item.actor_display_name ? (
                      <p className="mt-1 text-xs text-muted-foreground">{item.actor_display_name}</p>
                    ) : null}
                  </div>
                </li>
              )
            })}
          </ul>
        ) : (
          <EmptyState
            icon={History}
            title="Пока пусто"
            description="Здесь появятся подключения бота, команды, конфиги и другие действия на канале."
            className="border-0 bg-transparent shadow-none"
          />
        )}
      </div>
    </section>
  )
}

function BotModeratorDialog({
  actionBusy,
  botIsModerator,
  botLogin,
  isOpen,
  onAddModerator,
  onDeactivate,
  onClose,
}: {
  actionBusy: string | null
  botIsModerator: boolean
  botLogin: string
  isOpen: boolean
  onAddModerator: () => void
  onDeactivate: () => void
  onClose: () => void
}) {
  const busy = actionBusy === "make-moderator" || actionBusy === "deactivate-chat"

  return (
    <AppDialog
      open={isOpen}
      onClose={onClose}
      title="Бот подключён к каналу"
      description="Выдай модератора, чтобы бот мог отвечать в чате."
      footer={
        <>
          <Button type="button" variant="outline" onClick={onClose}>
            Позже
          </Button>
          <Button
            type="button"
            variant={botIsModerator ? "destructive" : "brand"}
            onClick={botIsModerator ? onDeactivate : onAddModerator}
            disabled={busy}
          >
            {busy ? (
              <Loader2 className="size-4 animate-spin" />
            ) : botIsModerator ? (
              <Radio className="size-4" />
            ) : (
              <ShieldCheck className="size-4" />
            )}
            {botIsModerator ? "Отключить от чата" : "Сделать модератором"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="panel-muted flex gap-3 border-[color-mix(in_srgb,var(--health-ok)_35%,var(--flaunt-border))] p-4 text-sm">
          <CheckCircle2 className="size-5 shrink-0 text-[var(--health-ok)]" />
          <span>Бот должен зайти в чат в ближайшее время.</span>
        </div>
        <p className="text-sm text-muted-foreground">
          Нажми кнопку ниже — сайт выдаст модератора аккаунту <span className="font-medium text-foreground">@{botLogin}</span>.
        </p>
        <div className="panel-muted p-3 font-mono text-sm">
          /mod {botLogin}
        </div>
      </div>
    </AppDialog>
  )
}

function DashboardPageSkeleton() {
  return (
    <PageShell className="space-y-8">
      <Skeleton className="h-20 w-full max-w-lg" />
      <Skeleton className="h-48 w-full" />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
      </div>
      <Skeleton className="h-24 w-full" />
      <div className="grid gap-6 xl:grid-cols-2">
        <Skeleton className="min-h-[28rem]" />
        <Skeleton className="min-h-[20rem]" />
      </div>
    </PageShell>
  )
}

function buildReadiness(data: DashboardPayload | null | undefined) {
  if (!data) return { ready: false }
  const ready = data.status.chat_connected && data.status.bot_is_moderator
  return { ready }
}

function formatQuizStatus(quiz: DashboardPayload["quiz"]) {
  if (quiz.paused) return "На паузе"
  if (quiz.is_active) return `Раунд · ${formatDuration(quiz.seconds_left)}`
  if (quiz.passive_mode && quiz.passive_waiting_for_live) return "Ждёт эфир"
  if (quiz.passive_mode && quiz.auto_rounds_stopped) return "Пассивный стоп"
  if (quiz.next_round_in > 0) return `След. раунд · ${formatDuration(quiz.next_round_in)}`
  if (quiz.passive_mode) return "Пассивный режим"
  return "Ожидание"
}

function formatDuration(seconds: number) {
  const safe = Math.max(0, seconds | 0)
  const mins = Math.floor(safe / 60)
  const secs = safe % 60
  return `${mins}:${secs.toString().padStart(2, "0")}`
}

function actionIcon(action: string): LucideIcon {
  const key = action.toLowerCase()
  if (key.includes("quiz")) return CircleHelp
  if (key.includes("chat") || key.includes("bot")) return Radio
  if (key.includes("timer")) return Timer
  if (key.includes("command")) return MessageSquareText
  if (key.includes("giveaway")) return Gift
  return CheckCircle2
}
