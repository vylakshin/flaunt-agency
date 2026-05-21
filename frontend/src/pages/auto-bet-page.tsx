import { ChevronDown, Copy, Crosshair, ExternalLink, Gamepad2, Loader2, Plus, RotateCcw, Trophy, X } from "lucide-react"
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react"

import { PageHeader } from "@/components/app/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Toast, type ToastNotice } from "@/components/ui/toast"
import { useJsonQuery } from "@/hooks/use-json-query"
import { fetchJson, requestJson } from "@/lib/api"
import type { AutoBetPayload } from "@/types/app"

type AutoBetForm = {
  dota2_enabled: boolean
  dota2_custom_questions_enabled: boolean
  dota2_custom_kills_enabled: boolean
  dota2_custom_deaths_enabled: boolean
  dota2_custom_assists_enabled: boolean
  dota2_custom_duration_enabled: boolean
  cs2_enabled: boolean
  cs2_custom_questions_enabled: boolean
  cs2_custom_win_enabled: boolean
  cs2_custom_kills_enabled: boolean
  cs2_custom_deaths_enabled: boolean
  cs2_custom_assists_enabled: boolean
  prediction_window_seconds: string
  prediction_title_template: string
}

type GsiInstallTab = "auto" | "manual"
type ActivePrediction = NonNullable<AutoBetPayload["active_prediction"]>
type ActiveOutcome = ActivePrediction["outcomes"][number]

const defaultForm: AutoBetForm = {
  dota2_enabled: false,
  dota2_custom_questions_enabled: false,
  dota2_custom_kills_enabled: true,
  dota2_custom_deaths_enabled: true,
  dota2_custom_assists_enabled: true,
  dota2_custom_duration_enabled: true,
  cs2_enabled: false,
  cs2_custom_questions_enabled: false,
  cs2_custom_win_enabled: true,
  cs2_custom_kills_enabled: true,
  cs2_custom_deaths_enabled: true,
  cs2_custom_assists_enabled: true,
  prediction_window_seconds: "120",
  prediction_title_template: "Матч {game}: победа?",
}

export function AutoBetPage() {
  const { data, isLoading, error, setData } = useJsonQuery<AutoBetPayload>("/api/app/autobet")
  const [form, setForm] = useState<AutoBetForm>(defaultForm)
  const [gsiInstallTab, setGsiInstallTab] = useState<GsiInstallTab>("auto")
  const [isManualOpen, setManualOpen] = useState(false)
  const [manualTitle, setManualTitle] = useState("")
  const [manualFirstOutcome, setManualFirstOutcome] = useState("Победа")
  const [manualSecondOutcome, setManualSecondOutcome] = useState("Поражение")
  const [manualWindow, setManualWindow] = useState("120")
  const [notice, setNotice] = useState<ToastNotice | null>(null)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [nowMs, setNowMs] = useState(() => Date.now())
  const [predictionClock, setPredictionClock] = useState<{ id: string; syncedAtMs: number; secondsRemaining: number }>({
    id: "",
    syncedAtMs: 0,
    secondsRemaining: 0,
  })
  const busyActionRef = useRef<string | null>(null)

  useEffect(() => {
    if (!data) return
    if (busyActionRef.current === "save") return
    document.title = `${data.user.login} — автоставка`
    setForm({
      dota2_enabled: data.settings.dota2_enabled,
      dota2_custom_questions_enabled: data.settings.dota2_custom_questions_enabled,
      dota2_custom_kills_enabled: data.settings.dota2_custom_kills_enabled,
      dota2_custom_deaths_enabled: data.settings.dota2_custom_deaths_enabled,
      dota2_custom_assists_enabled: data.settings.dota2_custom_assists_enabled,
      dota2_custom_duration_enabled: data.settings.dota2_custom_duration_enabled,
      cs2_enabled: data.settings.cs2_enabled,
      cs2_custom_questions_enabled: data.settings.cs2_custom_questions_enabled,
      cs2_custom_win_enabled: data.settings.cs2_custom_win_enabled,
      cs2_custom_kills_enabled: data.settings.cs2_custom_kills_enabled,
      cs2_custom_deaths_enabled: data.settings.cs2_custom_deaths_enabled,
      cs2_custom_assists_enabled: data.settings.cs2_custom_assists_enabled,
      prediction_window_seconds: String(data.settings.prediction_window_seconds),
      prediction_title_template: data.settings.prediction_title_template || "Матч {game}: победа?",
    })
    setManualWindow(String(data.settings.prediction_window_seconds || 120))
  }, [
    data?.settings.cs2_enabled,
    data?.settings.cs2_custom_questions_enabled,
    data?.settings.cs2_custom_win_enabled,
    data?.settings.cs2_custom_kills_enabled,
    data?.settings.cs2_custom_deaths_enabled,
    data?.settings.cs2_custom_assists_enabled,
    data?.settings.dota2_custom_assists_enabled,
    data?.settings.dota2_custom_deaths_enabled,
    data?.settings.dota2_custom_duration_enabled,
    data?.settings.dota2_custom_kills_enabled,
    data?.settings.dota2_custom_questions_enabled,
    data?.settings.dota2_enabled,
    data?.settings.prediction_title_template,
    data?.settings.prediction_window_seconds,
    data?.user.login,
  ])

  useEffect(() => {
    const timer = window.setInterval(async () => {
      if (busyActionRef.current) return
      try {
        await refreshAutoBetState()
      } catch {
        // Keep the last good state on transient polling errors.
      }
    }, data?.active_prediction ? 500 : 700)
    return () => window.clearInterval(timer)
  }, [busyAction, Boolean(data?.active_prediction), setData])

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  async function refreshAutoBetState() {
    const payload = await fetchJson<AutoBetPayload>("/api/app/autobet")
    setData(payload)
    return payload
  }

  async function runAction(action: string, run: () => Promise<void>) {
    busyActionRef.current = action
    setBusyAction(action)
    setNotice(null)
    try {
      await run()
    } catch (error) {
      setNotice({ type: "error", title: "Действие не выполнено", text: (error as Error).message })
    } finally {
      busyActionRef.current = null
      setBusyAction(null)
    }
  }

  async function saveSettings(nextForm: AutoBetForm = form) {
    setForm(nextForm)
    await runAction("save", async () => {
      const payload = await requestJson<AutoBetPayload>("/api/app/autobet/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dota2_enabled: nextForm.dota2_enabled,
          dota2_custom_questions_enabled: nextForm.dota2_custom_questions_enabled,
          dota2_custom_kills_enabled: nextForm.dota2_custom_kills_enabled,
          dota2_custom_deaths_enabled: nextForm.dota2_custom_deaths_enabled,
          dota2_custom_assists_enabled: nextForm.dota2_custom_assists_enabled,
          dota2_custom_duration_enabled: nextForm.dota2_custom_duration_enabled,
          cs2_enabled: nextForm.cs2_enabled,
          cs2_custom_questions_enabled: nextForm.cs2_custom_questions_enabled,
          cs2_custom_win_enabled: nextForm.cs2_custom_win_enabled,
          cs2_custom_kills_enabled: nextForm.cs2_custom_kills_enabled,
          cs2_custom_deaths_enabled: nextForm.cs2_custom_deaths_enabled,
          cs2_custom_assists_enabled: nextForm.cs2_custom_assists_enabled,
          prediction_window_seconds: Number.parseInt(nextForm.prediction_window_seconds, 10),
          prediction_title_template: nextForm.prediction_title_template,
        }),
      })
      setData(payload)
      setNotice({ type: "success", title: "Автоставка сохранена", text: "Настройки обновлены." })
    })
  }

  async function resolvePrediction(result: "win" | "loss" | "cancel") {
    await runAction(`resolve-${result}`, async () => {
      const payload = await requestJson<AutoBetPayload>("/api/app/autobet/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ result }),
      })
      setData(payload)
      await refreshAutoBetState()
      setNotice({
        type: result === "cancel" ? "warning" : "success",
        title: result === "win" ? "Закрыто первым ответом" : result === "loss" ? "Закрыто вторым ответом" : "Ставка отменена",
        text: "Результат ставки обновлён.",
      })
    })
  }

  async function openManualPrediction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    await runAction("manual", async () => {
      const payload = await requestJson<AutoBetPayload>("/api/app/autobet/manual", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          game_key: "dota2",
          title: manualTitle,
          first_outcome_title: manualFirstOutcome,
          second_outcome_title: manualSecondOutcome,
          prediction_window_seconds: Number.parseInt(manualWindow, 10),
        }),
      })
      setData(payload)
      await refreshAutoBetState()
      setManualOpen(false)
      setNotice({ type: "success", title: "Ставка открыта", text: "Новая ставка создана." })
    })
  }

  async function copyInstallCommand(value: string) {
    try {
      await navigator.clipboard.writeText(value)
      setNotice({ type: "success", title: "Команда скопирована", text: "Нажми Win+R, вставь команду и нажми Enter." })
    } catch {
      setNotice({ type: "error", title: "Не удалось скопировать", text: "Скопируй команду вручную из поля." })
    }
  }




  const isBusy = busyAction !== null
  const active = data?.active_prediction ?? null
  useEffect(() => {
    if (!active) {
      setPredictionClock({ id: "", syncedAtMs: 0, secondsRemaining: 0 })
      return
    }
    setPredictionClock({
      id: active.id,
      syncedAtMs: Date.now(),
      secondsRemaining: Math.max(0, Number(active.seconds_remaining || 0)),
    })
  }, [active?.id, active?.seconds_remaining])

  const firstOutcome = active?.outcomes?.[0]
  const secondOutcome = active?.outcomes?.[1]
  const activeTotalPoints = active?.total_channel_points ?? 0
  const firstPercent = activeTotalPoints > 0 ? Math.round(((firstOutcome?.channel_points ?? 0) / activeTotalPoints) * 100) : 50
  const secondPercent = activeTotalPoints > 0 ? 100 - firstPercent : 50
  const activeSecondsRemaining = active
    ? Math.max(0, predictionClock.secondsRemaining - Math.floor((nowMs - predictionClock.syncedAtMs) / 1000))
    : 0
  const activeIsClosed = Boolean(active) && activeSecondsRemaining <= 0
  const activeStatusLabel = active ? (activeIsClosed ? "Закрыта" : "Открыта") : "Нет ставки"

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-16 w-72" />
        <Skeleton className="h-72 w-full" />
      </div>
    )
  }

  if (error || !data) {
    return <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm">{error ?? "Не удалось загрузить автоставку."}</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <PageHeader title="Автоставка" description="Ручные и автоматические ставки для Dota 2 и CS." />
        <div className="flex flex-wrap gap-2">
          <Button type="button" disabled={Boolean(active) || isBusy} onClick={() => setManualOpen(true)}>
            <Plus className="size-4" />
            Добавить ставку
          </Button>
        </div>
      </div>

      <Toast notice={notice} onClose={() => setNotice(null)} />

      <div className="grid gap-4 md:grid-cols-2">
        <GameStatusCard
          game="Dota 2"
          autoEnabled={form.dota2_enabled}
          customEnabled={form.dota2_custom_questions_enabled}
          detail="Автоставка по матчу и кастомные вопросы по Dota 2."
        />
        <GameStatusCard
          game="CS"
          autoEnabled={form.cs2_enabled}
          customEnabled={form.cs2_custom_questions_enabled}
          detail="Автоставка по Competitive/Premier и кастомные вопросы по CS."
        />
      </div>

      <OverlaySetupCard overlayUrl={data.obs_overlay_url} />

      <Card>
        <CardHeader className="gap-4 md:flex-row md:items-start md:justify-between">
          <div>
            <CardTitle>Актуальная ставка на канале</CardTitle>
            <CardDescription>{active ? "Обновляется каждые несколько секунд." : "Активной ставки сейчас нет."}</CardDescription>
          </div>
          {active ? (
            <Badge variant={activeIsClosed ? "outline" : "success"}>{formatTimeLeft(activeSecondsRemaining)}</Badge>
          ) : (
            <Badge variant="outline">Нет ставки</Badge>
          )}
        </CardHeader>
        <CardContent>
          {active ? (
            <div className="space-y-6">
              {active.sync_error ? (
                <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">{active.sync_error}</div>
              ) : null}

              <div className="border-b pb-4">
                <div className="text-sm text-muted-foreground">{normalizeDisplayText(active.game_name, "Ставка")}</div>
                <div className="mt-1 text-lg font-semibold">{normalizeDisplayText(active.title, `Ставка по ${normalizeDisplayText(active.game_name, "игре")}`)}</div>
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
                  <span>{activeStatusLabel}</span>
                  <span>{formatNumber(active.total_channel_points)} баллов</span>
                  <span>{formatNumber(active.total_users)} участников</span>
                </div>
              </div>

              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_220px_minmax(0,1fr)] lg:items-center">
                <OutcomePanel outcome={firstOutcome} fallbackTitle={active.win_outcome_title || "Ответ 1"} tone="blue" />
                <div className="space-y-3 text-center">
                  <div className="mx-auto grid size-40 place-items-center rounded-full border bg-background shadow-sm">
                    <div>
                      <div className="text-3xl font-semibold">{formatNumber(active.total_channel_points)}</div>
                      <div className="text-xs text-muted-foreground">баллов всего</div>
                    </div>
                  </div>
                  <div className="flex h-4 overflow-hidden rounded-full bg-muted">
                    <div className="bg-sky-500 transition-all" style={{ width: `${firstPercent}%` }} />
                    <div className="bg-rose-500 transition-all" style={{ width: `${secondPercent}%` }} />
                  </div>
                  <div className="grid grid-cols-2 text-xs text-muted-foreground">
                    <span>{firstPercent}%</span>
                    <span>{secondPercent}%</span>
                  </div>
                </div>
                <OutcomePanel outcome={secondOutcome} fallbackTitle={active.loss_outcome_title || "Ответ 2"} tone="rose" />
              </div>

              <div className="grid gap-2 sm:grid-cols-3">
                <Button type="button" disabled={isBusy} onClick={() => void resolvePrediction("win")}>
                  <Trophy className="size-4" />
                  {normalizeDisplayText(active.win_outcome_title || firstOutcome?.title, "Ответ 1")}
                </Button>
                <Button type="button" variant="destructive" disabled={isBusy} onClick={() => void resolvePrediction("loss")}>
                  {normalizeDisplayText(active.loss_outcome_title || secondOutcome?.title, "Ответ 2")}
                </Button>
                <Button type="button" variant="outline" disabled={isBusy} onClick={() => void resolvePrediction("cancel")}>
                  <RotateCcw className="size-4" />
                  Отмена
                </Button>
              </div>
            </div>
          ) : (
              <div className="py-8 text-center">
                <div className="font-medium">Ставка не открыта</div>
                <div className="mt-1 text-sm text-muted-foreground">Нажми "Добавить ставку" или включи авто-Dota 2 ниже.</div>
              </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Настройка игр</CardTitle>
          <CardDescription>Здесь включаются автоставки и выбираются типы кастомных вопросов для Dota 2 и CS.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-6 xl:grid-cols-2">
          <GameSettingsSection title="Dota 2" description="Игра сама сообщает о начале и завершении матча. Когда приходит сигнал из клиента, бот открывает ставку и потом сам подводит итог.">
            <GameToggle
              checked={form.dota2_enabled}
              description="Бот ждёт сигнал от игры и открывает ставку, когда матч реально начался."
              disabled={busyAction === "save"}
              label="Автоставка"
              onChange={(checked) =>
                void saveSettings({
                  ...form,
                  dota2_enabled: checked,
                  dota2_custom_questions_enabled: checked ? form.dota2_custom_questions_enabled : false,
                })
              }
            />
            <GameToggle
              checked={form.dota2_custom_questions_enabled}
              description="Вместо победы или поражения бот выбирает вопрос по матчу: киллы, смерти, ассисты или длительность."
              disabled={!form.dota2_enabled || busyAction === "save"}
              label="Кастомные ставки"
              onChange={(checked) => void saveSettings({ ...form, dota2_custom_questions_enabled: checked })}
            />
            {form.dota2_custom_questions_enabled ? (
              <div className="border-t pt-4">
                <div className="font-medium">Типы кастомных ставок</div>
                <div className="mt-1 text-sm text-muted-foreground">Выбери, какие типы вопросов бот может открывать.</div>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <CustomMarketToggle checked={form.dota2_custom_kills_enabled} disabled={!form.dota2_custom_questions_enabled || busyAction === "save"} label="Киллы" onChange={(checked) => void saveSettings({ ...form, dota2_custom_kills_enabled: checked })} />
                  <CustomMarketToggle checked={form.dota2_custom_deaths_enabled} disabled={!form.dota2_custom_questions_enabled || busyAction === "save"} label="Смерти" onChange={(checked) => void saveSettings({ ...form, dota2_custom_deaths_enabled: checked })} />
                  <CustomMarketToggle checked={form.dota2_custom_assists_enabled} disabled={!form.dota2_custom_questions_enabled || busyAction === "save"} label="Ассисты" onChange={(checked) => void saveSettings({ ...form, dota2_custom_assists_enabled: checked })} />
                  <CustomMarketToggle checked={form.dota2_custom_duration_enabled} disabled={!form.dota2_custom_questions_enabled || busyAction === "save"} label="Длительность" onChange={(checked) => void saveSettings({ ...form, dota2_custom_duration_enabled: checked })} />
                </div>
              </div>
            ) : null}
          </GameSettingsSection>

          <GameSettingsSection title="CS" description="Игра сама сообщает о начале матча. Ставки открываются только в Competitive и Premier.">
            <GameToggle
              checked={form.cs2_enabled}
              description="Бот ждёт сигнал от игры и открывает ставку, когда матч реально начался."
              disabled={busyAction === "save"}
              label="Автоставка"
              onChange={(checked) =>
                void saveSettings({
                  ...form,
                  cs2_enabled: checked,
                  cs2_custom_questions_enabled: checked ? form.cs2_custom_questions_enabled : false,
                })
              }
            />
            <GameToggle
              checked={form.cs2_custom_questions_enabled}
              description="Вместо победы или поражения бот может выбрать вопрос на победу, киллы, смерти или ассисты."
              disabled={!form.cs2_enabled || busyAction === "save"}
              label="Кастомные ставки"
              onChange={(checked) => void saveSettings({ ...form, cs2_custom_questions_enabled: checked })}
            />
            {form.cs2_custom_questions_enabled ? (
              <div className="border-t pt-4">
                <div className="font-medium">Типы кастомных ставок</div>
                <div className="mt-1 text-sm text-muted-foreground">Выбери, какие типы вопросов бот может открывать.</div>
                <div className="mt-4 grid gap-3 md:grid-cols-2">
                  <CustomMarketToggle checked={form.cs2_custom_win_enabled} disabled={!form.cs2_custom_questions_enabled || busyAction === "save"} label="Победа" onChange={(checked) => void saveSettings({ ...form, cs2_custom_win_enabled: checked })} />
                  <CustomMarketToggle checked={form.cs2_custom_kills_enabled} disabled={!form.cs2_custom_questions_enabled || busyAction === "save"} label="Киллы" onChange={(checked) => void saveSettings({ ...form, cs2_custom_kills_enabled: checked })} />
                  <CustomMarketToggle checked={form.cs2_custom_deaths_enabled} disabled={!form.cs2_custom_questions_enabled || busyAction === "save"} label="Смерти" onChange={(checked) => void saveSettings({ ...form, cs2_custom_deaths_enabled: checked })} />
                  <CustomMarketToggle checked={form.cs2_custom_assists_enabled} disabled={!form.cs2_custom_questions_enabled || busyAction === "save"} label="Ассисты" onChange={(checked) => void saveSettings({ ...form, cs2_custom_assists_enabled: checked })} />
                </div>
              </div>
            ) : null}
          </GameSettingsSection>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>История ставок</CardTitle>
          <CardDescription>Последние 5 закрытых ставок по Dota 2 и CS.</CardDescription>
        </CardHeader>
        <CardContent>
          <BetHistory items={data.history} />
        </CardContent>
      </Card>

      <ConnectionPanel
        activeTab={gsiInstallTab}
        gsi={data.gsi}
        onCopy={copyInstallCommand}
        onTabChange={setGsiInstallTab}
      />

      <ManualPredictionDialog
        firstOutcome={manualFirstOutcome}
        isBusy={busyAction === "manual"}
        isOpen={isManualOpen}
        onClose={() => setManualOpen(false)}
        onFirstOutcomeChange={setManualFirstOutcome}
        onSecondOutcomeChange={setManualSecondOutcome}
        onSubmit={openManualPrediction}
        onTitleChange={setManualTitle}
        onWindowChange={setManualWindow}
        secondOutcome={manualSecondOutcome}
        title={manualTitle}
        windowSeconds={manualWindow}
      />
    </div>
  )
}

function OutcomePanel({
  fallbackTitle,
  outcome,
  tone,
}: {
  fallbackTitle: string
  outcome?: ActiveOutcome
  tone: "blue" | "rose"
}) {
  const borderClass = tone === "blue" ? "border-sky-500/40 bg-sky-500/10" : "border-rose-500/40 bg-rose-500/10"
  const topPredictor = outcome?.top_predictor_display_name || outcome?.top_predictor_login || "Пока нет"
  return (
    <div className={`px-4 py-3 ${borderClass}`}>
      <div className="text-sm text-muted-foreground">Вариант</div>
      <div className="mt-1 text-lg font-semibold">{normalizeDisplayText(outcome?.title || fallbackTitle, fallbackTitle)}</div>
      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <Metric label="Баллы" value={formatNumber(outcome?.channel_points ?? 0)} />
        <Metric label="Люди" value={formatNumber(outcome?.users ?? 0)} />
      </div>
      <div className="mt-4 border-t pt-3 text-sm">
        <div className="text-xs text-muted-foreground">Больше всех поставил</div>
        <div className="mt-1 font-medium">{normalizeDisplayText(topPredictor, "Пока нет")}</div>
        <div className="text-xs text-muted-foreground">{formatNumber(outcome?.top_predictor_points ?? 0)} баллов</div>
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-semibold">{value}</div>
    </div>
  )
}

function GameStatusCard({
  autoEnabled,
  customEnabled,
  detail,
  game,
}: {
  autoEnabled: boolean
  customEnabled: boolean
  detail: string
  game: string
}) {
  const Icon = game === "Dota 2" ? Gamepad2 : Crosshair
  const accentClass = autoEnabled ? "bg-emerald-500/15 text-emerald-400" : "bg-amber-500/15 text-amber-300"

  return (
    <Card className="border-border/80 bg-card/80">
      <CardContent className="flex items-start gap-4 p-4">
        <div className={`mt-0.5 flex size-12 shrink-0 items-center justify-center rounded-2xl ${accentClass}`}>
          <Icon className="size-5" />
        </div>
        <div className="min-w-0 space-y-1">
          <div className="text-sm text-muted-foreground">{game}</div>
          <div className="text-xl font-semibold leading-tight">{autoEnabled ? "Автоставка включена" : "Автоставка выключена"}</div>
          <div className="text-sm text-muted-foreground">{customEnabled ? "Кастомные ставки включены" : "Кастомные ставки выключены"}</div>
          <div className="text-xs text-muted-foreground">{detail}</div>
        </div>
      </CardContent>
    </Card>
  )
}

function GameSettingsSection({
  children,
  description,
  title,
}: {
  children: ReactNode
  description: string
  title: string
}) {
  return (
    <section className="rounded-lg border p-5">
      <div className="mb-4">
        <div className="font-semibold">{title}</div>
        <div className="mt-1 text-sm text-muted-foreground">{description}</div>
      </div>
      <div className="divide-y">{children}</div>
    </section>
  )
}

function BetHistory({ items }: { items: AutoBetPayload["history"] }) {
  return (
    <div>
      {items.length ? (
        <div className="divide-y">
          {items.map((item) => (
            <div key={item.id} className="grid gap-3 py-4 text-sm md:grid-cols-[minmax(0,1fr)_140px_120px] md:items-center">
              <div className="min-w-0">
                <div className="truncate font-medium">{item.title || "Ставка"}</div>
                <div className="mt-1 text-xs text-muted-foreground">{normalizeDisplayText(item.game_name, "Dota 2")}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Исход</div>
                <div className="font-medium">{normalizeDisplayText(formatHistoryOutcome(item.outcome_title, item.status), "Завершена")}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Баллы</div>
                <div className="font-medium">{formatNumber(item.total_channel_points)}</div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="py-2 text-sm text-muted-foreground">История появится после закрытия первой ставки.</div>
      )}
    </div>
  )
}

function OverlaySetupCard({ overlayUrl }: { overlayUrl: string }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <details className="group">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-4 [&::-webkit-details-marker]:hidden">
            <div>
              <div className="font-semibold">Browser Source для OBS</div>
              <div className="mt-1 text-sm text-muted-foreground">Скопируй ссылку оверлея и добавь её в OBS как отдельный браузерный источник.</div>
            </div>
            <ChevronDown className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
          </summary>
          <div className="mt-4 space-y-4 border-t pt-4">
            <OverlayUrlField overlayUrl={overlayUrl} />
            <div className="space-y-2 text-sm text-muted-foreground">
              <div>1. Создай в OBS новый источник <span className="text-foreground">Browser Source</span>.</div>
              <div>2. Поставь размер <span className="text-foreground">1920×1080</span>.</div>
              <div>3. Вставь ссылку из поля выше.</div>
              <div>4. Размести источник <span className="text-foreground">по центру экрана</span> и не растягивай его вручную на весь экран.</div>
            </div>
          </div>
        </details>
      </CardContent>
    </Card>
  )
}

function OverlayUrlField({ overlayUrl }: { overlayUrl: string }) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(overlayUrl)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2200)
    } catch {
      setCopied(false)
    }
  }

  function openOverlayUrl() {
    window.open(overlayUrl, "_blank", "noopener,noreferrer")
  }

  return (
    <div className="relative">
      <Input className="h-11 pr-24 font-mono text-sm" readOnly value={copied ? "Ссылка скопирована" : overlayUrl} />
      <div className="absolute right-1 top-1/2 flex -translate-y-1/2 items-center gap-1">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-9"
          title="Скопировать ссылку"
          aria-label="Скопировать ссылку"
          onClick={() => void handleCopy()}
        >
          <Copy className="size-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-9"
          title="Открыть overlay"
          aria-label="Открыть overlay"
          onClick={openOverlayUrl}
        >
          <ExternalLink className="size-4" />
        </Button>
      </div>
    </div>
  )
}
function ConnectionPanel({
  activeTab,
  gsi,
  onCopy,
  onTabChange,
}: {
  activeTab: GsiInstallTab
  gsi: AutoBetPayload["gsi"]
  onCopy: (value: string) => void
  onTabChange: (tab: GsiInstallTab) => void
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Подключение игры</CardTitle>
        <CardDescription>Разовая настройка на компьютере с игрой для Dota 2 и CS2.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <details className="group" open>
          <summary className="flex cursor-pointer list-none items-center justify-between gap-4 py-3 [&::-webkit-details-marker]:hidden">
            <div>
              <div className="font-medium">Подключение игры</div>
              <div className="mt-1 text-sm text-muted-foreground">Установка файлов для Dota 2 и CS2 на компьютере с игрой.</div>
            </div>
            <ChevronDown className="size-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
          </summary>
          <div className="space-y-5 border-t pt-4 text-sm">
            <div className="inline-grid rounded-lg border bg-muted/30 p-1 sm:grid-cols-2">
              <button
                type="button"
                className={activeTab === "auto" ? "rounded-md bg-background px-4 py-2 text-sm font-medium shadow-sm" : "rounded-md px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground"}
                onClick={() => onTabChange("auto")}
              >
                В один клик
              </button>
              <button
                type="button"
                className={activeTab === "manual" ? "rounded-md bg-background px-4 py-2 text-sm font-medium shadow-sm" : "rounded-md px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground"}
                onClick={() => onTabChange("manual")}
              >
                По шагам
              </button>
            </div>

            {activeTab === "auto" ? (
              <div className="space-y-3">
                <div className="font-medium">Быстрая установка</div>
                <div className="mt-1 text-muted-foreground">Нажми Win+R, вставь команду и нажми Enter.</div>
                <div className="mt-3 flex gap-2">
                  <Input className="font-mono text-xs" readOnly value={gsi.install_command} />
                  <Button type="button" size="icon" variant="outline" onClick={() => onCopy(gsi.install_command)} aria-label="Скопировать команду">
                    <Copy className="size-4" />
                  </Button>
                </div>
                <div className="mt-2 text-xs text-muted-foreground">
                  Команда сама подготовит подключение для Dota 2 и CS2. Для Dota 2 она ещё попробует добавить нужный параметр запуска.
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="font-medium">Ручная установка</div>
                <div className="text-muted-foreground">Если быстрый способ не сработал, можно настроить всё вручную по шагам ниже.</div>
                <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
                  <li>Для Dota 2 открой папку: <span className="text-foreground">game/dota/cfg</span>.</li>
                  <li>Создай папку <span className="text-foreground">gamestate_integration</span>, если её нет.</li>
                  <li>Создай файл <span className="text-foreground">{gsi.config_filename}</span>.</li>
                  <li>Вставь в файл текст ниже и сохрани.</li>
                  <li>В свойствах Dota 2 добавь параметр запуска <span className="text-foreground">-gamestateintegration</span>.</li>
                  <li>Перезапусти Dota 2 и дождись первого матча.</li>
                </ol>
                <div className="mt-3 font-medium">Текст файла для Dota 2</div>
                <pre className="max-h-80 overflow-auto rounded-md bg-background p-3 text-xs text-foreground">{gsi.config_text}</pre>
                <ol className="list-decimal space-y-1 pl-5 pt-3 text-muted-foreground">
                  <li>Для CS2 открой папку: <span className="text-foreground">Counter-Strike Global Offensive/game/csgo/cfg</span>.</li>
                  <li>Создай файл <span className="text-foreground">{gsi.cs2_config_filename}</span>.</li>
                  <li>Вставь в файл текст ниже, сохрани и перезапусти CS2.</li>
                </ol>
                <div className="mt-3 font-medium">Текст файла для CS2</div>
                <pre className="max-h-80 overflow-auto rounded-md bg-background p-3 text-xs text-foreground">{gsi.cs2_config_text}</pre>
              </div>
            )}
          </div>
        </details>

      </CardContent>
    </Card>
  )
}

function ManualPredictionDialog({
  firstOutcome,
  isBusy,
  isOpen,
  onClose,
  onFirstOutcomeChange,
  onSecondOutcomeChange,
  onSubmit,
  onTitleChange,
  onWindowChange,
  secondOutcome,
  title,
  windowSeconds,
}: {
  firstOutcome: string
  isBusy: boolean
  isOpen: boolean
  onClose: () => void
  onFirstOutcomeChange: (value: string) => void
  onSecondOutcomeChange: (value: string) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  onTitleChange: (value: string) => void
  onWindowChange: (value: string) => void
  secondOutcome: string
  title: string
  windowSeconds: string
}) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-background/80 p-4 backdrop-blur-sm" role="presentation" onMouseDown={onClose}>
      <div
        aria-modal="true"
        className="w-full max-w-xl overflow-hidden rounded-lg border bg-card text-card-foreground shadow-xl"
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-4 border-b p-4">
          <div>
            <h2 className="text-lg font-semibold">Добавить ставку</h2>
            <p className="text-sm text-muted-foreground">Укажи вопрос, ответы и время до закрытия.</p>
          </div>
          <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label="Закрыть окно">
            <X className="size-4" />
          </Button>
        </div>

        <form className="space-y-5 p-4" onSubmit={onSubmit}>
          <label className="space-y-2">
            <span className="text-sm font-medium">Вопрос</span>
            <Input autoFocus maxLength={45} value={title} onChange={(event) => onTitleChange(event.target.value)} />
          </label>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="space-y-2">
              <span className="text-sm font-medium">Ответ 1</span>
              <Input maxLength={25} value={firstOutcome} onChange={(event) => onFirstOutcomeChange(event.target.value)} />
            </label>
            <label className="space-y-2">
              <span className="text-sm font-medium">Ответ 2</span>
              <Input maxLength={25} value={secondOutcome} onChange={(event) => onSecondOutcomeChange(event.target.value)} />
            </label>
          </div>

          <label className="space-y-2">
            <span className="text-sm font-medium">До закрытия</span>
            <Input inputMode="numeric" max={1800} min={30} type="number" value={windowSeconds} onChange={(event) => onWindowChange(event.target.value)} />
          </label>

          <div className="flex justify-end gap-2 border-t pt-4">
            <Button type="button" variant="outline" onClick={onClose}>
              Отмена
            </Button>
            <Button type="submit" disabled={isBusy}>
              {isBusy ? <Loader2 className="size-4 animate-spin" /> : <Plus className="size-4" />}
              Открыть
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

function GameToggle({
  checked,
  description,
  label,
  onChange,
  disabled = false,
}: {
  checked: boolean
  description: string
  disabled?: boolean
  label: string
  onChange: (checked: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-4">
      <div className="min-w-0">
        <div className="font-medium">{label}</div>
        <div className="mt-1 text-sm text-muted-foreground">{description}</div>
      </div>
      <Switch checked={checked} disabled={disabled} onCheckedChange={onChange} />
    </div>
  )
}

function CustomMarketToggle({
  checked,
  disabled,
  label,
  onChange,
}: {
  checked: boolean
  disabled?: boolean
  label: string
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="flex items-center justify-between gap-3 border-b py-3 text-sm last:border-b-0">
      <span className={disabled ? "text-muted-foreground" : "font-medium"}>{label}</span>
      <Switch checked={checked} disabled={disabled} onCheckedChange={onChange} />
    </label>
  )
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("ru-RU").format(Number.isFinite(value) ? value : 0)
}

function formatTimeLeft(seconds: number) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "Закрыта"
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return `${minutes}:${String(rest).padStart(2, "0")}`
}

function repairBrokenRussian(value: string) {
  const raw = String(value || "")
  if (!raw || (!raw.includes("Р") && !raw.includes("С"))) return raw
  try {
    const bytes = Uint8Array.from(Array.from(raw).map((char) => char.charCodeAt(0) & 0xff))
    const decoded = new TextDecoder("utf-8", { fatal: true }).decode(bytes)
    return decoded || raw
  } catch {
    return raw
  }
}

function looksBrokenText(value: string) {
  const raw = String(value || "").trim()
  if (!raw) return true
  if (raw.includes("�")) return true
  const questionCount = (raw.match(/\?/g) || []).length
  if (questionCount >= 2) return true
  return false
}

function normalizeDisplayText(value: string | null | undefined, fallback: string) {
  const repaired = repairBrokenRussian(String(value || ""))
  if (looksBrokenText(repaired)) return fallback
  return repaired
}

function formatHistoryOutcome(outcomeTitle: string, status: string) {
  const normalizedStatus = String(status || "").trim().toUpperCase()
  const normalizedOutcome = String(outcomeTitle || "").trim()
  if (normalizedStatus === "CANCELED") return "Отмена"
  if (normalizedOutcome && !looksLikeBrokenRussian(normalizedOutcome)) return normalizedOutcome
  if (normalizedStatus === "RESOLVED") return "Завершена"
  if (normalizedStatus === "LOCKED") return "Закрыта"
  return "Завершена"
}

function looksLikeBrokenRussian(value: string) {
  return /Р[\u0400-\u04ffA-Za-z]|С[\u0400-\u04ffA-Za-z]|Ѓ|�/.test(value)
}

function formatGameTime(seconds: number) {
  if (!Number.isFinite(seconds) || seconds === 0) return "0:00"
  const sign = seconds < 0 ? "-" : ""
  const absSeconds = Math.abs(seconds)
  const minutes = Math.floor(absSeconds / 60)
  const rest = absSeconds % 60
  return `${sign}${minutes}:${String(rest).padStart(2, "0")}`
}




