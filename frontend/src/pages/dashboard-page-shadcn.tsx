import {
  Bot,
  CalendarDays,
  CheckCircle2,
  Clock3,
  CircleAlert,
  Copy,
  ExternalLink,
  FileJson,
  Gauge,
  Loader2,
  PlayCircle,
  Radio,
  ShieldCheck,
  SquareDashedMousePointer,
  StopCircle,
  Trophy,
  Trash2,
  Upload,
  X,
} from "lucide-react"
import { useEffect, useMemo, useState, type ChangeEvent, type FormEvent, type KeyboardEvent } from "react"

import {
  dashboardSettingsFromPayload,
  GameSettingsCard,
  serializeDashboardSettings,
  syncDashboardSettingsChatMode,
  type DashboardSettingsForm,
  type SettingsSaveState,
} from "@/components/app/game-settings-card"
import { PageHeader } from "@/components/app/page-header"
import { PageShell } from "@/components/app/page-shell"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import { Skeleton } from "@/components/ui/skeleton"
import { Toast, type ToastNotice } from "@/components/ui/toast"
import { useJsonQuery } from "@/hooks/use-json-query"
import { requestForm, requestJson } from "@/lib/api"
import { cn } from "@/lib/utils"
import type { DashboardPayload, MutationResult } from "@/types/app"

function OverlayUrlField({ overlayUrl }: { overlayUrl: string }) {
  const [copied, setCopied] = useState(false)

  async function copyOverlayUrl() {
    await navigator.clipboard?.writeText(overlayUrl)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 2200)
  }

  function openOverlayUrl() {
    window.open(overlayUrl, "_blank", "noopener,noreferrer")
  }

  return (
    <div className="relative">
      <Input className={cn("h-11 pr-24 font-mono text-sm", copied && "text-foreground")} readOnly value={copied ? "Ссылка скопирована" : overlayUrl} />
      <div className="absolute right-1 top-1/2 flex -translate-y-1/2 items-center gap-1">
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-9"
          title="Скопировать ссылку"
          aria-label="Скопировать ссылку"
          onClick={() => void copyOverlayUrl()}
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

function formatQuizDuration(seconds: number) {
  const safe = Math.max(0, seconds)
  const mins = Math.floor(safe / 60)
  const secs = safe % 60
  return `${mins}:${secs.toString().padStart(2, "0")}`
}

function quizStatusLabel(quiz: DashboardPayload["quiz"]) {
  if (quiz.paused) return "Пауза"
  if (quiz.is_active) return `Раунд · ${formatQuizDuration(quiz.seconds_left)}`
  if (quiz.passive_mode && quiz.passive_waiting_for_live) return "Ожидание эфира"
  if (quiz.passive_mode && quiz.passive_result_seconds_left > 0) return `Итог раунда · ${quiz.passive_result_seconds_left} с`
  if (quiz.passive_mode && quiz.auto_rounds_stopped) return "Пассивный режим остановлен"
  if (quiz.next_round_in > 0) return `Ожидание · ${formatQuizDuration(quiz.next_round_in)}`
  if (quiz.passive_mode) return "Пассивный режим"
  return "Ожидание раунда"
}

export function QuizPage() {
  const { data, isLoading, error, refetch } = useJsonQuery<DashboardPayload>("/api/app/dashboard")
  const [notice, setNotice] = useState<ToastNotice | null>(null)
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  const [seasonTitle, setSeasonTitle] = useState("")
  const [seasonEndsAt, setSeasonEndsAt] = useState("")
  const [uploadName, setUploadName] = useState("")
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadInputKey, setUploadInputKey] = useState(0)
  const [isUploadModalOpen, setUploadModalOpen] = useState(false)
  const [formState, setFormState] = useState<DashboardSettingsForm | null>(() => (data ? dashboardSettingsFromPayload(data) : null))
  const [settingsSaveState, setSettingsSaveState] = useState<SettingsSaveState>("idle")
  const [lastSavedSettings, setLastSavedSettings] = useState(() => (data ? serializeDashboardSettings(dashboardSettingsFromPayload(data)) : ""))

  useEffect(() => {
    if (data) document.title = `${data.user.login} — викторина`
  }, [data])

  useEffect(() => {
    const timer = window.setInterval(() => {
      void refetch()
    }, 2000)
    return () => window.clearInterval(timer)
  }, [refetch])

  const activeConfigLabel = useMemo(() => {
    if (!data) return "Источник не выбран"
    return data.configs.find((config) => config.is_active)?.name ?? "Источник не выбран"
  }, [data])

  const customConfigCount = data ? data.configs.filter((config) => !config.is_standard).length : 0
  const configProgress = data ? (customConfigCount / data.limits.custom_configs_max) * 100 : 0

  if (data && !formState) {
    const nextSettings = dashboardSettingsFromPayload(data)
    setFormState(nextSettings)
    setLastSavedSettings(serializeDashboardSettings(nextSettings))
    setSettingsSaveState("idle")
  }

  async function withAction(action: string, run: () => Promise<void>) {
    setActionBusy(action)
    setNotice(null)
    try {
      await run()
    } catch (error) {
      setNotice({ type: "error", title: "Действие не выполнено", text: (error as Error).message })
    } finally {
      setActionBusy(null)
    }
  }

  function updateSettings(next: Partial<DashboardSettingsForm>) {
    if (!formState) return
    const nextFormState = syncDashboardSettingsChatMode({ ...formState, ...next })
    setFormState(nextFormState)
    void saveSettingsSnapshot(nextFormState)
  }

  async function saveSettingsSnapshot(snapshot: DashboardSettingsForm) {
    const serialized = serializeDashboardSettings(snapshot)
    if (serialized === lastSavedSettings) return

    setSettingsSaveState("saving")
    try {
      const answerCooldown = Number.parseFloat(snapshot.answer_cooldown_seconds)
      if (!Number.isFinite(answerCooldown)) throw new Error("Укажи корректный кулдаун ответа.")
      await requestJson<MutationResult>("/api/app/dashboard/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          answer_cooldown_seconds: answerCooldown,
          command_access: snapshot.command_access,
          overlay_theme: snapshot.overlay_theme,
          turbo_mode: snapshot.turbo_mode,
          quiz_passive_mode: snapshot.quiz_passive_mode,
          quiet_mode: snapshot.quiet_mode,
          chat_questions_enabled: snapshot.chat_questions_enabled,
          chat_outcomes_enabled: snapshot.chat_outcomes_enabled,
        }),
      })
      setLastSavedSettings(serialized)
      setSettingsSaveState("saved")
      setNotice(null)
    } catch (error) {
      setSettingsSaveState("error")
      setNotice({ type: "error", title: "Настройки не сохранены", text: (error as Error).message })
    }
  }

  async function selectConfig(selectedSource: string) {
    await withAction(`select-config-${selectedSource}`, async () => {
      await requestJson<MutationResult>("/api/app/dashboard/questions/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ selected_source: selectedSource }),
      })
      await refetch()
      setNotice({ type: "success", title: "База вопросов переключена", text: "Новые раунды будут брать вопросы из выбранного источника." })
    })
  }

  async function deleteConfig(configId: number) {
    if (!window.confirm("Удалить этот конфиг вопросов?")) return
    await withAction(`delete-config-${configId}`, async () => {
      await requestJson<MutationResult>("/api/app/dashboard/questions/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config_id: configId }),
      })
      await refetch()
      setNotice({ type: "success", title: "Конфиг удалён", text: "Если удалённый конфиг был активным, игра переключится на доступный fallback." })
    })
  }

  async function uploadConfig(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!uploadFile) {
      setNotice({ type: "error", title: "Файл не выбран", text: "Выбери JSON-файл с вопросами." })
      return
    }

    await withAction("upload-config", async () => {
      const formData = new FormData()
      formData.set("config_name", uploadName)
      formData.set("questions_file", uploadFile)
      await requestForm<MutationResult>("/api/app/dashboard/questions/upload", formData)
      setUploadName("")
      setUploadFile(null)
      setUploadInputKey((current) => current + 1)
      setUploadModalOpen(false)
      await refetch()
      setNotice({ type: "success", title: "Конфиг загружен", text: "Новый JSON сохранён и сразу выбран активным." })
    })
  }

  async function startSeason(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!seasonEndsAt) {
      setNotice({ type: "error", title: "Укажи дату окончания", text: "Без времени окончания сезон не запустится." })
      return
    }

    await withAction("season-start", async () => {
      await requestJson<MutationResult>("/api/app/quiz/season/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: seasonTitle,
          ends_at: new Date(seasonEndsAt).toISOString(),
        }),
      })
      setSeasonTitle("")
      await refetch()
      setNotice({ type: "success", title: "Сезон запущен", text: "Теперь очки недели копятся в отдельном топе." })
    })
  }

  async function startQuizRound() {
    await withAction("quiz-start", async () => {
      const result = await requestJson<MutationResult>("/api/app/quiz/start", { method: "POST" })
      await refetch()
      setNotice({ type: "success", title: "Раунд запущен", text: result.message ?? "Новый раунд начался." })
    })
  }

  async function stopQuiz() {
    if (!window.confirm("Остановить викторину и сбросить очки текущей сессии?")) return
    await withAction("quiz-stop", async () => {
      const result = await requestJson<MutationResult>("/api/app/quiz/stop", { method: "POST" })
      await refetch()
      setNotice({ type: "success", title: "Викторина остановлена", text: result.message ?? "Игра остановлена." })
    })
  }

  async function finishSeason(seasonId?: number) {
    if (!window.confirm("Завершить текущий сезон и заморозить топ?")) return
    await withAction("season-finish", async () => {
      await requestJson<MutationResult>("/api/app/quiz/season/finish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ season_id: seasonId ?? null }),
      })
      await refetch()
      setNotice({ type: "success", title: "Сезон завершён", text: "Финальный топ сохранён в истории." })
    })
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    setUploadFile(event.target.files?.[0] ?? null)
  }

  if (error || (!isLoading && !data)) {
    return (
      <Alert variant="destructive">
        <CircleAlert className="mb-3 size-5" />
        <AlertTitle>Не удалось загрузить кабинет</AlertTitle>
        <AlertDescription>{error ?? "Сервер вернул пустой ответ."}</AlertDescription>
      </Alert>
    )
  }

  if (isLoading || !data || !formState) return <DashboardSkeleton />

  return (
    <PageShell wide>
      <PageHeader title="Викторина" description="Конфиги вопросов и overlay для игры." />

      <Toast notice={notice} onClose={() => setNotice(null)} />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatusCard icon={Radio} label="Чат" value={data.status.chat_connected ? "Подключён" : "Не подключён"} tone={data.status.chat_connected ? "success" : "destructive"} />
        <StatusCard icon={ShieldCheck} label="Модерация" value={data.status.bot_is_moderator ? data.status.bot_status_online_label : data.status.bot_status_offline_label} tone={data.status.bot_is_moderator ? "success" : "warning"} />
        <StatusCard icon={Gauge} label="Режим" value={data.settings.turbo_mode ? "Турбо" : data.settings.quiz_passive_mode ? "Пассивный" : "Обычный"} tone={data.settings.turbo_mode || data.settings.quiz_passive_mode ? "success" : "default"} />
        <StatusCard icon={FileJson} label="Вопросы" value={activeConfigLabel} tone="default" />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2">
                <PlayCircle className="size-5" />
                Состояние игры
              </CardTitle>
              <CardDescription>Живой статус раунда, ожидания и overlay. Обновляется каждые 2 секунды.</CardDescription>
            </div>
            <Badge variant={data.quiz.is_active ? "success" : "outline"}>{quizStatusLabel(data.quiz)}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-3 rounded-xl border bg-muted/20 p-4 text-sm md:grid-cols-2">
            <div>
              <div className="text-muted-foreground">Категория</div>
              <div className="font-medium">{data.quiz.category || "—"}</div>
            </div>
            <div>
              <div className="text-muted-foreground">Подсказка</div>
              <div className="font-medium">{data.quiz.hint || "—"}</div>
            </div>
            <div className="md:col-span-2">
              <div className="text-muted-foreground">Слово</div>
              <div className="font-mono font-medium">{data.quiz.masked_answer || "—"}</div>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="button" onClick={() => void startQuizRound()} disabled={actionBusy !== null || data.quiz.is_active}>
              {actionBusy === "quiz-start" ? <Loader2 className="size-4 animate-spin" /> : <PlayCircle className="size-4" />}
              Запустить раунд
            </Button>
            <Button type="button" variant="destructive" onClick={() => void stopQuiz()} disabled={actionBusy !== null}>
              {actionBusy === "quiz-stop" ? <Loader2 className="size-4 animate-spin" /> : <StopCircle className="size-4" />}
              Остановить игру
            </Button>
          </div>
        </CardContent>
      </Card>

      {data.status.chat_status_text ? (
        <Alert variant="warning">
          <AlertTitle>Статус подключения</AlertTitle>
          <AlertDescription>{data.status.chat_status_text}</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <SquareDashedMousePointer className="size-5" />
            Browser Source для OBS
          </CardTitle>
          <CardDescription>Скопируй ссылку и добавь её в OBS как Browser Source для викторины.</CardDescription>
        </CardHeader>
        <CardContent>
          <OverlayUrlField overlayUrl={data.overlay_url} />
        </CardContent>
      </Card>

      <SeasonCard
        actionBusy={actionBusy}
        data={data}
        finishSeason={finishSeason}
        seasonEndsAt={seasonEndsAt}
        seasonTitle={seasonTitle}
        setSeasonEndsAt={setSeasonEndsAt}
        setSeasonTitle={setSeasonTitle}
        startSeason={startSeason}
      />

      <QuestionsCard
        actionBusy={actionBusy}
        configProgress={configProgress}
        customConfigCount={customConfigCount}
        data={data}
        deleteConfig={deleteConfig}
        handleFileChange={handleFileChange}
        isUploadModalOpen={isUploadModalOpen}
        selectConfig={selectConfig}
        setUploadModalOpen={setUploadModalOpen}
        uploadConfig={uploadConfig}
        uploadInputKey={uploadInputKey}
        uploadName={uploadName}
        setUploadName={setUploadName}
      />

      <GameSettingsCard data={data} formState={formState} isSaving={settingsSaveState === "saving"} settingsSaveState={settingsSaveState} updateSettings={updateSettings} />
    </PageShell>
  )
}

function QuestionsCard({
  actionBusy,
  configProgress,
  customConfigCount,
  data,
  deleteConfig,
  handleFileChange,
  isUploadModalOpen,
  selectConfig,
  setUploadModalOpen,
  setUploadName,
  uploadConfig,
  uploadInputKey,
  uploadName,
}: {
  actionBusy: string | null
  configProgress: number
  customConfigCount: number
  data: DashboardPayload
  deleteConfig: (configId: number) => void
  handleFileChange: (event: ChangeEvent<HTMLInputElement>) => void
  isUploadModalOpen: boolean
  selectConfig: (selectedSource: string) => void
  setUploadModalOpen: (value: boolean) => void
  setUploadName: (value: string) => void
  uploadConfig: (event: FormEvent<HTMLFormElement>) => void
  uploadInputKey: number
  uploadName: string
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <FileJson className="size-5" />
              Конфиги вопросов
            </CardTitle>
            <CardDescription>До {data.limits.custom_configs_max} кастомных JSON-наборов и общие пакеты, которые выдаёт админка.</CardDescription>
          </div>
          <Button type="button" onClick={() => setUploadModalOpen(true)} disabled={data.limits.custom_limit_reached}>
            <Upload className="size-4" />
            {data.limits.custom_limit_reached ? "Лимит конфигов" : "Добавить конфиг"}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Заполнено</span>
              <span className="font-medium">
              {customConfigCount}/{data.limits.custom_configs_max}
              </span>
          </div>
          <Progress value={configProgress} />
        </div>

        {data.configs.length ? (
          <div className="space-y-3">
            {data.configs.map((config) => (
              <QuestionSourceCard
                key={config.id}
                active={config.is_active}
                description={config.kind_label}
                isBusy={actionBusy === `select-config-${config.id}` || actionBusy === `delete-config-${config.id}`}
                label={config.name}
                onDelete={config.is_standard ? undefined : () => deleteConfig(config.id)}
                onSelect={() => selectConfig(String(config.id))}
              />
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed bg-muted/20 p-4 text-sm text-muted-foreground">
            Сейчас нет ни одного доступного пака вопросов. Загрузить кастомный JSON можно здесь, а общие пакеты появляются только после выдачи из админки.
          </div>
        )}

        <UploadConfigDialog
          actionBusy={actionBusy}
          handleFileChange={handleFileChange}
          isOpen={isUploadModalOpen}
          onOpenChange={setUploadModalOpen}
          setUploadName={setUploadName}
          uploadConfig={uploadConfig}
          uploadInputKey={uploadInputKey}
          uploadName={uploadName}
        />
      </CardContent>
    </Card>
  )
}

function SeasonCard({
  actionBusy,
  data,
  finishSeason,
  seasonEndsAt,
  seasonTitle,
  setSeasonEndsAt,
  setSeasonTitle,
  startSeason,
}: {
  actionBusy: string | null
  data: DashboardPayload
  finishSeason: (seasonId?: number) => void
  seasonEndsAt: string
  seasonTitle: string
  setSeasonEndsAt: (value: string) => void
  setSeasonTitle: (value: string) => void
  startSeason: (event: FormEvent<HTMLFormElement>) => void
}) {
  const activeSeason = data.quiz.season && data.quiz.season.status !== "finished" ? data.quiz.season : null
  const latestFinishedSeason = data.quiz.season && data.quiz.season.status === "finished" ? data.quiz.season : null
  const historyItems = latestFinishedSeason ? [latestFinishedSeason, ...data.quiz.season_history] : data.quiz.season_history
  const sessionTop = data.quiz.top_players ?? []

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Trophy className="size-5" />
              Сезон викторины
            </CardTitle>
            <CardDescription>Недельный или любой другой отрезок с отдельным топом, который не сбрасывается при перезапуске игры.</CardDescription>
          </div>
          {activeSeason ? <Badge variant={activeSeason.status === "active" ? "success" : "outline"}>{seasonStatusLabel(activeSeason.status)}</Badge> : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {activeSeason ? (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
            <div className="space-y-4 rounded-xl border p-4">
              <div className="space-y-1">
                <div className="text-lg font-semibold">{activeSeason.title}</div>
                <div className="text-sm text-muted-foreground">
                  Старт: {formatSeasonDate(activeSeason.starts_at)} • Конец: {formatSeasonDate(activeSeason.ends_at)}
                </div>
                {activeSeason.status === "finished" && activeSeason.closed_at ? (
                  <div className="text-sm text-muted-foreground">Финал зафиксирован: {formatSeasonDate(activeSeason.closed_at)}</div>
                ) : null}
              </div>

              {activeSeason.status !== "finished" ? (
                <div className="rounded-lg bg-muted/40 p-3 text-sm">
                  <div className="flex items-center gap-2 font-medium">
                    <Clock3 className="size-4" />
                    Осталось: {formatDuration(activeSeason.seconds_left)}
                  </div>
                  <div className="mt-1 text-muted-foreground">Очки автоматически копятся до указанного времени.</div>
                </div>
              ) : null}

              <div className="space-y-2">
                <div className="text-sm font-medium">Топ сезона</div>
                {activeSeason.top_players.length ? (
                  <div className="space-y-2">
                    {activeSeason.top_players.map((player, index) => (
                      <div key={`${player.username}-${index}`} className="flex items-center justify-between rounded-lg border px-3 py-2 text-sm">
                        <div className="min-w-0">
                          <div className="font-medium">{index + 1}. {player.username}</div>
                          <div className="text-muted-foreground">{player.wins} побед</div>
                        </div>
                        <div className="font-semibold">{player.points}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed bg-muted/30 p-4 text-sm text-muted-foreground">Пока никто не набрал очки в этом сезоне.</div>
                )}
              </div>

              {activeSeason.status !== "finished" ? (
                <div className="flex justify-end">
                  <Button type="button" variant="outline" onClick={() => void finishSeason(activeSeason.id)} disabled={actionBusy !== null}>
                    {actionBusy === "season-finish" ? <Loader2 className="size-4 animate-spin" /> : <StopCircle className="size-4" />}
                    Завершить сезон
                  </Button>
                </div>
              ) : null}
            </div>

            <div className="space-y-4">
              <div className="rounded-xl border p-4">
                <div className="mb-3 text-sm font-medium">Текущий игровой топ</div>
                {sessionTop.length ? (
                  <div className="space-y-2">
                    {sessionTop.map((player, index) => (
                      <div key={`${player.username}-${index}`} className="flex items-center justify-between text-sm">
                        <span>{index + 1}. {player.username}</span>
                        <span className="font-medium">{player.points}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">Этот локальный топ живёт до сброса викторины. Сезонный топ выше остаётся до конца сезона.</div>
                )}
              </div>

              <div className="rounded-xl border p-4">
                <div className="mb-3 text-sm font-medium">История сезонов</div>
                {historyItems.length ? (
                  <div className="space-y-3">
                    {historyItems.map((season) => (
                      <div key={season.id} className="rounded-lg border p-3">
                        <div className="font-medium">{season.title}</div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {formatSeasonDate(season.starts_at)} • {formatSeasonDate(season.closed_at || season.ends_at)}
                        </div>
                        {season.top_players.length ? (
                          <div className="mt-2 space-y-1 text-sm">
                            {season.top_players.map((player, index) => (
                              <div key={`${season.id}-${player.username}-${index}`} className="flex items-center justify-between">
                                <span>{index + 1}. {player.username}</span>
                                <span className="font-medium">{player.points}</span>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="mt-2 text-sm text-muted-foreground">Без победителей.</div>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-sm text-muted-foreground">История появится после первого завершённого сезона.</div>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
            <form className="space-y-4 rounded-xl border p-4" onSubmit={startSeason}>
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="season-title-input">
                  Название сезона
                </label>
                <Input
                  id="season-title-input"
                  placeholder="Например: Викторина недели"
                  value={seasonTitle}
                  onChange={(event) => setSeasonTitle(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="season-end-input">
                  Закончить
                </label>
                <Input
                  id="season-end-input"
                  type="datetime-local"
                  value={seasonEndsAt}
                  onChange={(event) => setSeasonEndsAt(event.target.value)}
                />
              </div>
              <Button type="submit" disabled={actionBusy !== null}>
                {actionBusy === "season-start" ? <Loader2 className="size-4 animate-spin" /> : <CalendarDays className="size-4" />}
                Запустить сезон
              </Button>
            </form>

            <div className="rounded-xl border border-dashed bg-muted/30 p-4 text-sm text-muted-foreground">
              Сезонный топ не зависит от обычного сброса викторины. Запусти сезон, укажи время окончания, и победители недели сохранятся в истории автоматически.
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function formatSeasonDate(value: string) {
  if (!value) return "—"
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString()
}

function formatDuration(totalSeconds: number) {
  const seconds = Math.max(0, totalSeconds | 0)
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days > 0) return `${days} д ${hours} ч`
  if (hours > 0) return `${hours} ч ${minutes} мин`
  return `${minutes} мин`
}

function seasonStatusLabel(status: string) {
  if (status === "active") return "Активен"
  if (status === "scheduled") return "По расписанию"
  return "Завершён"
}

function UploadConfigDialog({
  actionBusy,
  handleFileChange,
  isOpen,
  onOpenChange,
  setUploadName,
  uploadConfig,
  uploadInputKey,
  uploadName,
}: {
  actionBusy: string | null
  handleFileChange: (event: ChangeEvent<HTMLInputElement>) => void
  isOpen: boolean
  onOpenChange: (value: boolean) => void
  setUploadName: (value: string) => void
  uploadConfig: (event: FormEvent<HTMLFormElement>) => void
  uploadInputKey: number
  uploadName: string
}) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-background/80 p-4 backdrop-blur-sm" role="presentation" onMouseDown={() => onOpenChange(false)}>
      <div
        aria-modal="true"
        className="w-full max-w-lg rounded-xl border bg-card p-6 text-card-foreground shadow-xl"
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">Добавить конфиг</h2>
            <p className="mt-1 text-sm text-muted-foreground">Укажи название и JSON-файл. После загрузки конфиг станет активным.</p>
          </div>
          <Button type="button" variant="ghost" size="icon" onClick={() => onOpenChange(false)} aria-label="Закрыть попап">
            <X className="size-4" />
          </Button>
        </div>

        <form className="grid gap-4" onSubmit={uploadConfig}>
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="config-name-input">
              Название
            </label>
            <Input id="config-name-input" placeholder="Например: Кино и сериалы" value={uploadName} onChange={(event) => setUploadName(event.target.value)} />
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="config-file-input">
              JSON-файл
            </label>
            <Input id="config-file-input" key={uploadInputKey} accept=".json,application/json" type="file" onChange={handleFileChange} />
          </div>

          <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Отмена
            </Button>
            <Button type="submit" disabled={actionBusy === "upload-config"}>
              {actionBusy === "upload-config" ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
              Загрузить
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

function DashboardSkeleton() {
  return (
    <PageShell wide>
      <Skeleton className="h-16 w-96" />
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
      <Skeleton className="h-96 w-full" />
    </PageShell>
  )
}

function StatusCard({
  icon: Icon,
  label,
  tone,
  value,
}: {
  icon: typeof Bot
  label: string
  tone: "default" | "success" | "warning" | "destructive"
  value: string
}) {
  return (
    <Card className="h-full">
      <CardContent className="flex h-full items-center gap-4 p-4">
        <div
          className={cn(
            "flex size-11 shrink-0 items-center justify-center rounded-xl",
            tone === "success" && "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
            tone === "warning" && "bg-amber-500/15 text-amber-700 dark:text-amber-300",
            tone === "destructive" && "bg-destructive/15 text-destructive",
            tone === "default" && "bg-secondary text-secondary-foreground"
          )}
        >
          <Icon className="size-5" />
        </div>
        <div className="min-w-0">
          <div className="text-sm text-muted-foreground">{label}</div>
          <div className="truncate font-medium">{value}</div>
        </div>
      </CardContent>
    </Card>
  )
}

function QuestionSourceCard({
  active,
  description,
  isBusy,
  label,
  onDelete,
  onSelect,
}: {
  active: boolean
  description: string
  isBusy: boolean
  label: string
  onDelete?: () => void
  onSelect: () => void
}) {
  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (active || isBusy) return
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault()
      onSelect()
    }
  }

  return (
    <div
      className={cn(
        "h-28 rounded-xl border bg-card p-4 transition-colors",
        active ? "border-primary bg-accent/50" : "cursor-pointer hover:bg-accent/50",
        isBusy && "pointer-events-none opacity-70"
      )}
      onClick={() => {
        if (!active && !isBusy) onSelect()
      }}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={active || isBusy ? -1 : 0}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate font-medium">{label}</div>
          <div className="mt-1 truncate text-sm text-muted-foreground">{description}</div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          {active ? <Badge variant="success">Активна</Badge> : <Badge variant="outline">Не выбрана</Badge>}
          {isBusy ? <Loader2 className="size-4 animate-spin text-muted-foreground" /> : null}
          {onDelete ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="text-destructive hover:text-destructive"
              disabled={isBusy}
              onClick={(event) => {
                event.stopPropagation()
                onDelete()
              }}
            >
              <Trash2 className="size-4" />
              Удалить
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function EmptyState({
  description,
  icon: Icon,
  title,
}: {
  description: string
  icon: typeof Bot
  title: string
}) {
  return (
    <div className="rounded-xl border border-dashed bg-muted/30 p-6 text-center">
      <div className="mx-auto flex size-11 items-center justify-center rounded-xl bg-background">
        <Icon className="size-5 text-muted-foreground" />
      </div>
      <div className="mt-3 font-medium">{title}</div>
      <div className="mt-1 text-sm text-muted-foreground">{description}</div>
    </div>
  )
}
