import { Loader2, Play, RotateCcw, Search, Square, Trash2, Trophy } from "lucide-react"
import { useEffect, useMemo, useState } from "react"

import { PageHeader } from "@/components/app/page-header"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Toast, type ToastNotice } from "@/components/ui/toast"
import { fetchJson, requestJson } from "@/lib/api"
import { useJsonQuery } from "@/hooks/use-json-query"
import type { GiveawayState, GiveawaysPayload } from "@/types/app"

type GiveawayForm = {
  giveaway_type: "active" | "keyword" | "points"
  keyword: string
  chat_announcements: boolean
  points_reward_title: string
  points_reward_cost: number
  points_allow_multiple_entries: boolean
  multipliers: GiveawayState["multipliers"]
}

export function GiveawaysPage() {
  const { data, isLoading, error, setData } = useJsonQuery<GiveawaysPayload>("/api/app/giveaways")
  const [notice, setNotice] = useState<ToastNotice | null>(null)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [chatEmbedMode, setChatEmbedMode] = useState<"embed" | "popout">("embed")
  const [chatLoadState, setChatLoadState] = useState<"loading" | "loaded" | "timeout">("loading")
  const [chatReloadKey, setChatReloadKey] = useState(0)
  const [wheelMode, setWheelMode] = useState<"normal" | "elimination">("normal")
  const [spinSeconds, setSpinSeconds] = useState(8)
  const [wheelSplit, setWheelSplit] = useState(10)
  const [wheelRotation, setWheelRotation] = useState(0)
  const [isWheelOpen, setWheelOpen] = useState(false)
  const [hideEliminatedLots, setHideEliminatedLots] = useState(false)
  const [form, setForm] = useState<GiveawayForm>({
    giveaway_type: "active",
    keyword: "",
    chat_announcements: false,
    points_reward_title: "Участвовать в розыгрыше",
    points_reward_cost: 100,
    points_allow_multiple_entries: false,
    multipliers: { default: 1, follower: 1, vip: 1, subscriber: 1 },
  })

  useEffect(() => {
    if (!data) return
    document.title = `${data.user.login} — розыгрыши`
    setForm({
      giveaway_type: data.state.giveaway_type,
      keyword: data.state.keyword,
      chat_announcements: data.state.chat_announcements,
      points_reward_title: data.state.points_reward_title,
      points_reward_cost: data.state.points_reward_cost,
      points_allow_multiple_entries: data.state.points_allow_multiple_entries,
      multipliers: data.state.multipliers,
    })
  }, [data?.user.login])

  useEffect(() => {
    const timer = window.setInterval(async () => {
      if (busyAction === "wheel") return
      try {
        const payload = await fetchJson<GiveawaysPayload>("/api/app/giveaways")
        setData(payload)
      } catch {
        // Keep the last good state on transient polling errors.
      }
    }, 2000)
    return () => window.clearInterval(timer)
  }, [busyAction, setData])

  useEffect(() => {
    setChatLoadState("loading")
    const timer = window.setTimeout(() => {
      setChatLoadState((current) => (current === "loading" ? "timeout" : current))
    }, 9000)
    return () => window.clearTimeout(timer)
  }, [chatEmbedMode, chatReloadKey, data?.user.login])

  const participants = useMemo(() => {
    const query = search.trim().toLowerCase()
    const items = data?.state.participants ?? []
    const eliminated = new Set(data?.state.wheel_eliminated_logins ?? [])
    const visibleItems = hideEliminatedLots ? items.filter((item) => !eliminated.has(item.login)) : items
    if (!query) return visibleItems
    return visibleItems.filter((item) => item.login.includes(query) || item.display_name.toLowerCase().includes(query))
  }, [data?.state.participants, data?.state.wheel_eliminated_logins, hideEliminatedLots, search])

  async function saveSettings() {
    const payload = await requestJson<GiveawaysPayload>("/api/app/giveaways/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    })
    setData(payload)
    return payload
  }

  async function runAction(action: string, run: () => Promise<void>) {
    setBusyAction(action)
    setNotice(null)
    try {
      await run()
    } catch (error) {
      setNotice({ type: "error", title: "Действие не выполнено", text: (error as Error).message })
    } finally {
      setBusyAction(null)
    }
  }

  async function toggleRunning(nextRunning: boolean) {
    await runAction("toggle", async () => {
      await saveSettings()
      const payload = await requestJson<GiveawaysPayload>("/api/app/giveaways/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ running: nextRunning }),
      })
      setData(payload)
      setNotice({
        type: "success",
        title: nextRunning ? "Розыгрыш запущен" : "Розыгрыш остановлен",
        text: nextRunning && form.giveaway_type === "points" ? "Награда за баллы подключена. Участники попадут в список после покупки награды." : nextRunning ? "Бот начал собирать участников из чата." : "Сбор участников остановлен.",
      })
    })
  }

  async function togglePointsReward() {
    await runAction("reward", async () => {
      await saveSettings()
      const payload = await requestJson<GiveawaysPayload>("/api/app/giveaways/reward/toggle", { method: "POST" })
      setData(payload)
      setNotice(
        payload.state.points_reward_ready
          ? { type: "success", title: "Награда создана", text: `${payload.state.points_reward_title} готова для розыгрыша.` }
          : { type: "warning", title: "Награда удалена", text: "Покупки этой награды больше не будут добавлять участников." }
      )
    })
  }

  async function roll() {
    await runAction("roll", async () => {
      await saveSettings()
      const payload = await requestJson<GiveawaysPayload>("/api/app/giveaways/roll", { method: "POST" })
      setData(payload)
      setNotice({ type: "success", title: "Победитель выбран", text: payload.state.winner ? `@${payload.state.winner.login}` : "Готово." })
    })
  }

  async function spinWheel() {
    await runAction("wheel", async () => {
      await saveSettings()
      const currentSegments = buildWheelSegments(data?.state.participants ?? [], data?.state.wheel_eliminated_logins ?? [], wheelMode, wheelSplit)
      const payload = await requestJson<GiveawaysPayload>("/api/app/giveaways/wheel/spin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: wheelMode }),
      })
      const resultLogin = payload.state.wheel_last_result?.login ?? payload.state.winner?.login ?? ""
      const targetAngle = getWheelTargetAngle(currentSegments, resultLogin)
      const spinDuration = Math.max(2, Math.min(60, spinSeconds))
      setWheelRotation((current) => current + 360 * Math.max(4, spinDuration) + (360 - targetAngle))
      await new Promise((resolve) => window.setTimeout(resolve, spinDuration * 1000))
      setData(payload)
      setNotice({
        type: "success",
        title: wheelMode === "elimination" && payload.state.winner?.login !== resultLogin ? "Лот выбыл" : "Колесо остановилось",
        text: resultLogin ? `RANDOM.ORG выбрал @${resultLogin}.` : "Готово.",
      })
    })
  }

  async function clearGiveaway() {
    if (!window.confirm("Очистить участников и победителя?")) return
    await runAction("clear", async () => {
      const payload = await requestJson<GiveawaysPayload>("/api/app/giveaways/clear", { method: "POST" })
      setData(payload)
      setNotice({ type: "warning", title: "Розыгрыш очищен", text: "Список участников и сообщения победителя очищены." })
    })
  }

  async function removeParticipant(login: string) {
    await runAction(`remove:${login}`, async () => {
      const payload = await requestJson<GiveawaysPayload>("/api/app/giveaways/participants/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ login }),
      })
      setData(payload)
      setNotice({ type: "warning", title: "Участник удалён", text: `@${login} не попадёт в список до очистки розыгрыша.` })
    })
  }

  function updateMultiplier(key: keyof GiveawayState["multipliers"], value: string) {
    const parsed = Number.parseFloat(value)
    setForm((current) => ({
      ...current,
      multipliers: {
        ...current.multipliers,
        [key]: Number.isFinite(parsed) ? parsed : 1,
      },
    }))
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-16 w-72" />
        <Skeleton className="h-[520px] w-full" />
      </div>
    )
  }

  if (error || !data) {
    return <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm">{error ?? "Не удалось загрузить розыгрыши."}</div>
  }

  const isBusy = busyAction !== null
  const state = data.state
  const wheelSegments = buildWheelSegments(state.participants, state.wheel_eliminated_logins, wheelMode, wheelSplit)
  const eliminatedLogins = new Set(state.wheel_eliminated_logins)
  const totalParticipantChance = state.participants
    .filter((participant) => wheelMode !== "elimination" || !eliminatedLogins.has(participant.login))
    .reduce((sum, participant) => sum + Math.max(0, participant.multiplier), 0)
  const twitchChannel = encodeURIComponent(data.user.login)
  const chatParents = getTwitchChatParents()
  const embedChatParams = chatParents.map((parent) => `parent=${encodeURIComponent(parent)}`).join("&")
  const twitchEmbedChatUrl = `https://www.twitch.tv/embed/${twitchChannel}/chat?${embedChatParams}&darkpopout`
  const twitchPopoutChatUrl = `https://www.twitch.tv/popout/${twitchChannel}/chat?popout=`
  const twitchChatUrl = chatEmbedMode === "embed" ? twitchEmbedChatUrl : twitchPopoutChatUrl

  return (
    <div className="space-y-6">
      <PageHeader title="Розыгрыши" description="Собирай участников по активности, слову или покупке награды за баллы." />

      <Toast notice={notice} onClose={() => setNotice(null)} />

      <div className="grid min-h-[620px] gap-4 xl:grid-cols-[minmax(280px,0.75fr)_minmax(520px,1.55fr)_minmax(340px,0.85fr)]">
        <Card className="min-h-full">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle>Участники</CardTitle>
              <Badge variant="outline">{state.participants.length}</Badge>
            </div>
            <CardDescription>Кто попал в текущий розыгрыш.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input className="pl-9" placeholder="Поиск участников..." value={search} onChange={(event) => setSearch(event.target.value)} />
            </div>
            {wheelMode === "elimination" ? (
              <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
                <input
                  type="checkbox"
                  className="size-4 accent-primary"
                  checked={hideEliminatedLots}
                  onChange={(event) => setHideEliminatedLots(event.target.checked)}
                />
                Скрыть выбывшие лоты
              </label>
            ) : null}
            <div className="max-h-[460px] space-y-2 overflow-y-auto pr-1">
              {participants.length ? (
                participants.map((participant) => {
                  const isEliminated = state.wheel_eliminated_logins.includes(participant.login)
                  return (
                  <div key={participant.login} className={isEliminated ? "flex items-center justify-between gap-3 rounded-lg border bg-background/50 p-3 opacity-55" : "flex items-center justify-between gap-3 rounded-lg border bg-background p-3"}>
                    <div className="min-w-0 flex-1">
                      <div className={isEliminated ? "truncate font-medium line-through decoration-2" : "truncate font-medium"}>{participant.display_name}</div>
                      <div className={isEliminated ? "truncate text-xs text-muted-foreground line-through" : "truncate text-xs text-muted-foreground"}>@{participant.login} · {participant.message_count} сообщ.{isEliminated ? " · выбыл" : ""}</div>
                    </div>
                    <Badge className="shrink-0" variant="outline">
                      {isEliminated ? "выбыл" : totalParticipantChance > 0 ? `${((Math.max(0, participant.multiplier) / totalParticipantChance) * 100).toFixed(1)}%` : `${participant.multiplier}x`}
                    </Badge>
                    <Button
                      type="button"
                      size="icon"
                      variant="ghost"
                      className="size-8 shrink-0 text-muted-foreground hover:text-destructive"
                      onClick={() => void removeParticipant(participant.login)}
                      disabled={busyAction === `remove:${participant.login}`}
                      aria-label={`Удалить ${participant.display_name} из участников`}
                    >
                      {busyAction === `remove:${participant.login}` ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                    </Button>
                  </div>
                  )
                })
              ) : (
                <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">Участников пока нет</div>
              )}
            </div>
          </CardContent>
        </Card>

        <Card className="min-h-full">
          <CardHeader>
            <div className="flex items-start justify-between gap-3">
              <div>
                <CardTitle>{isWheelOpen ? "Колесо" : state.winner ? "Победитель" : "Настройки"}</CardTitle>
                <CardDescription>
                  {isWheelOpen
                    ? "RANDOM.ORG выбирает результат, а колесо показывает шансы участников."
                    : state.winner
                      ? "После ролла здесь остаются только победитель и его новые сообщения."
                      : "Тип розыгрыша и множители победы."}
                </CardDescription>
              </div>
              <Badge variant={state.running ? "success" : "outline"}>{state.running ? "Запущен" : "Остановлен"}</Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-6">
            {isWheelOpen ? (
              <WheelPanel
                eliminatedLogins={state.wheel_eliminated_logins}
                isBusy={busyAction === "wheel"}
                lastResult={state.wheel_last_result}
                lastSource={state.wheel_last_source}
                mode={wheelMode}
                onBack={() => setWheelOpen(false)}
                onModeChange={setWheelMode}
                onSpin={() => void spinWheel()}
                rotation={wheelRotation}
                segments={wheelSegments}
                spinSeconds={spinSeconds}
                split={wheelSplit}
                winner={state.winner}
                onSpinSecondsChange={setSpinSeconds}
                onSplitChange={setWheelSplit}
              />
            ) : state.winner ? (
              <>
                <section className="space-y-4 rounded-xl border bg-background p-5">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <div className="text-sm text-muted-foreground">Победитель</div>
                      <div className="text-2xl font-semibold">{state.winner.display_name}</div>
                      <div className="text-sm text-muted-foreground">@{state.winner.login} · {state.winner.multiplier}x</div>
                    </div>
                    <Trophy className="size-12 text-primary" />
                  </div>
                  <div className="max-h-[420px] min-h-[280px] space-y-2 overflow-y-auto rounded-lg border bg-card p-3">
                    {state.winner_messages.length ? (
                      state.winner_messages.map((message, index) => (
                        <div key={`${message.created_at}-${index}`} className="rounded-md bg-muted/50 p-2 text-sm">
                          <div className="text-xs text-muted-foreground">{message.created_at}</div>
                          <div>{message.text}</div>
                        </div>
                      ))
                    ) : (
                      <div className="grid min-h-[240px] place-items-center text-center text-sm text-muted-foreground">Новые сообщения победителя появятся здесь.</div>
                    )}
                  </div>
                </section>

                <div className="flex flex-col gap-2 border-t pt-4 sm:flex-row sm:items-center sm:justify-between">
                  <Button type="button" variant="outline" onClick={() => void clearGiveaway()} disabled={isBusy}>
                    <Trash2 className="size-4" />
                    Очистить
                  </Button>
                  <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
                    <GiveawayRunButton isBusy={busyAction === "toggle"} isRunning={state.running} onClick={() => void toggleRunning(!state.running)} />
                    <Button type="button" variant="outline" onClick={() => setWheelOpen(true)} disabled={isBusy}>
                      Колесо
                    </Button>
                    <Button type="button" variant="outline" onClick={() => void roll()} disabled={isBusy}>
                      {busyAction === "roll" ? <Loader2 className="size-4 animate-spin" /> : <RotateCcw className="size-4" />}
                      Рерол
                    </Button>
                  </div>
                </div>
              </>
            ) : (
              <>
                <section className="space-y-3">
                  <div className="text-sm font-medium">Тип розыгрыша</div>
                  <div className="grid gap-3 lg:grid-cols-3">
                    <GiveawayTypeButton
                      active={form.giveaway_type === "active"}
                      description="Участник попадает в список после первого сообщения."
                      label="Активный юзер"
                      onClick={() => setForm((current) => ({ ...current, giveaway_type: "active" }))}
                    />
                    <GiveawayTypeButton
                      active={form.giveaway_type === "keyword"}
                      description="Участник попадает в список, если написал нужное слово."
                      label="По слову"
                      onClick={() => setForm((current) => ({ ...current, giveaway_type: "keyword" }))}
                    />
                    <GiveawayTypeButton
                      active={form.giveaway_type === "points"}
                      description="Участник попадает в список после покупки награды за баллы."
                      label="За баллы"
                      onClick={() => setForm((current) => ({ ...current, giveaway_type: "points" }))}
                    />
                  </div>
                  {form.giveaway_type === "keyword" ? (
                    <label className="space-y-2">
                      <span className="text-sm font-medium text-muted-foreground">Кейворд</span>
                      <Input placeholder="Например: !участвую" value={form.keyword} onChange={(event) => setForm((current) => ({ ...current, keyword: event.target.value }))} />
                    </label>
                  ) : null}
                  {form.giveaway_type === "points" ? (
                    <div className="grid gap-3 rounded-lg border bg-background p-4 sm:grid-cols-[1fr_160px]">
                      <label className="space-y-2">
                        <span className="text-sm font-medium text-muted-foreground">Название награды</span>
                        <Input
                          maxLength={45}
                          placeholder="Участвовать в розыгрыше"
                          value={form.points_reward_title}
                          onChange={(event) => setForm((current) => ({ ...current, points_reward_title: event.target.value }))}
                        />
                      </label>
                      <label className="space-y-2">
                        <span className="text-sm font-medium text-muted-foreground">Стоимость</span>
                        <Input
                          min="1"
                          type="number"
                          value={form.points_reward_cost}
                          onChange={(event) => setForm((current) => ({ ...current, points_reward_cost: Number.parseInt(event.target.value, 10) || 1 }))}
                        />
                      </label>
                      <div className="flex flex-col gap-3 text-sm text-muted-foreground sm:col-span-2 sm:flex-row sm:items-center sm:justify-between">
                        <span>
                          Создай награду заранее, потом запускай розыгрыш. Если розыгрыш остановлен, покупки этой награды будут возвращаться.
                          {state.points_reward_ready ? ` Текущая награда подключена: ${state.points_reward_title}.` : ""}
                          {state.points_reward_ready
                            ? state.points_subscription_ready
                              ? " Покупки отслеживаются."
                              : " Покупки пока не отслеживаются, нажми Удалить награду и создай её снова."
                            : ""}
                        </span>
                        <Button
                          type="button"
                          variant={state.points_reward_ready ? "destructive" : "outline"}
                          size="sm"
                          className="shrink-0"
                          onClick={() => void togglePointsReward()}
                          disabled={busyAction === "reward" || isBusy}
                        >
                          {busyAction === "reward" ? <Loader2 className="size-4 animate-spin" /> : state.points_reward_ready ? <Trash2 className="size-4" /> : <Trophy className="size-4" />}
                          {state.points_reward_ready ? "Удалить награду" : "Создать награду"}
                        </Button>
                      </div>
                      <label className="flex cursor-pointer items-start justify-between gap-4 rounded-lg border bg-card p-4 text-left sm:col-span-2">
                        <span className="space-y-1">
                          <span className="block font-medium">Повторные покупки увеличивают шанс</span>
                          <span className="block text-sm text-muted-foreground">
                            Если включено, каждая новая покупка награды добавляет ещё один билет в розыгрыш. Если выключено, зритель может купить награду только один раз, а остальные покупки автоматически возвращаются.
                          </span>
                        </span>
                        <Switch
                          checked={form.points_allow_multiple_entries}
                          onCheckedChange={(checked) => setForm((current) => ({ ...current, points_allow_multiple_entries: checked }))}
                          aria-label="Повторные покупки увеличивают шанс"
                        />
                      </label>
                    </div>
                  ) : null}
                  <label className="mt-6 flex cursor-pointer items-start justify-between gap-4 rounded-lg border bg-background p-4">
                    <span className="space-y-1">
                      <span className="block font-medium">Уведомление в чате</span>
                      <span className="block text-sm text-muted-foreground">Если включено, после ролла бот отправит в чат: “Победитель в розыгрыше - @победитель”.</span>
                    </span>
                    <input
                      type="checkbox"
                      className="mt-1 size-4 accent-primary"
                      checked={form.chat_announcements}
                      onChange={(event) => setForm((current) => ({ ...current, chat_announcements: event.target.checked }))}
                      aria-label="Уведомление в чате"
                    />
                  </label>
                </section>

                <section className="space-y-3">
                  <div>
                    <div className="font-medium">Множитель победы</div>
                    <div className="text-sm text-muted-foreground">По дефолту все значения стоят на 1x. Если у зрителя несколько ролей, берётся самый большой множитель.</div>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <MultiplierField label="Обычные участники" value={form.multipliers.default} onChange={(value) => updateMultiplier("default", value)} />
                    <MultiplierField label="Фоловеры" value={form.multipliers.follower} onChange={(value) => updateMultiplier("follower", value)} />
                    <MultiplierField label="VIP" value={form.multipliers.vip} onChange={(value) => updateMultiplier("vip", value)} />
                    <MultiplierField label="Платные подписчики" value={form.multipliers.subscriber} onChange={(value) => updateMultiplier("subscriber", value)} />
                  </div>
                </section>

                <div className="flex flex-col gap-2 border-t pt-4 sm:flex-row sm:items-center sm:justify-between">
                  <Button type="button" variant="outline" onClick={() => void clearGiveaway()} disabled={isBusy}>
                    <Trash2 className="size-4" />
                    Очистить
                  </Button>
                  <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
                    <GiveawayRunButton isBusy={busyAction === "toggle"} isRunning={state.running} onClick={() => void toggleRunning(!state.running)} />
                    <Button type="button" variant="outline" onClick={() => setWheelOpen(true)} disabled={isBusy}>
                      Колесо
                    </Button>
                    <Button type="button" onClick={() => void roll()} disabled={isBusy}>
                      {busyAction === "roll" ? <Loader2 className="size-4 animate-spin" /> : <Trophy className="size-4" />}
                      Заролить
                    </Button>
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card className="min-h-full overflow-hidden">
          <CardContent className="p-0">
            <TwitchChatPanel
              channelLogin={data.user.login}
              externalUrl={twitchPopoutChatUrl}
              loadState={chatLoadState}
              mode={chatEmbedMode}
              onLoad={() => setChatLoadState("loaded")}
              onRetry={() => {
                setChatLoadState("loading")
                setChatReloadKey((key) => key + 1)
              }}
              onUsePopout={() => setChatEmbedMode("popout")}
              reloadKey={chatReloadKey}
              src={twitchChatUrl}
            />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

type WheelSegment = {
  login: string
  displayName: string
  multiplier: number
  percent: number
  color: string
  start: number
  end: number
}

function WheelPanel({
  eliminatedLogins,
  isBusy,
  lastResult,
  lastSource,
  mode,
  onBack,
  onModeChange,
  onSpin,
  onSpinSecondsChange,
  onSplitChange,
  rotation,
  segments,
  spinSeconds,
  split,
  winner,
}: {
  eliminatedLogins: string[]
  isBusy: boolean
  lastResult: GiveawayState["wheel_last_result"]
  lastSource: string
  mode: "normal" | "elimination"
  onBack: () => void
  onModeChange: (mode: "normal" | "elimination") => void
  onSpin: () => void
  onSpinSecondsChange: (value: number) => void
  onSplitChange: (value: number) => void
  rotation: number
  segments: WheelSegment[]
  spinSeconds: number
  split: number
  winner: GiveawayState["winner"]
}) {
  const gradient = segments.length
    ? `conic-gradient(from -90deg, ${segments.map((segment) => `${segment.color} ${segment.start}deg ${segment.end}deg`).join(", ")})`
    : "conic-gradient(from -90deg, hsl(var(--muted)) 0deg 360deg)"
  const title = winner ? `Победитель: ${winner.display_name}` : lastResult ? `${mode === "elimination" ? "Выбыл" : "Выбран"}: ${lastResult.display_name}` : "Победитель"
  const labelSegments = segments.filter((segment) => segment.end - segment.start >= 8).slice(0, 80)

  return (
    <section className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm text-muted-foreground">Настройки колеса и результат RANDOM.ORG.</div>
        <Button type="button" variant="outline" size="sm" onClick={onBack} disabled={isBusy}>
          Назад
        </Button>
      </div>
      <div className="space-y-5 rounded-xl border bg-background p-4">
      <div className="grid gap-6 xl:grid-cols-[minmax(320px,1fr)_260px]">
        <div className="flex flex-col items-center justify-center gap-4">
          <div className="text-center text-2xl font-semibold">{title}</div>
          <div className="relative aspect-square w-full max-w-[560px]">
            <div className="absolute left-1/2 top-0 z-20 h-0 w-0 -translate-x-1/2 -translate-y-1 border-x-[11px] border-t-[28px] border-x-transparent border-t-white drop-shadow-[0_3px_5px_rgba(0,0,0,0.85)]" />
            <div
              className="absolute inset-0 rounded-full border-4 border-foreground/80 shadow-2xl transition-transform ease-out"
              style={{
                background: gradient,
                transform: `rotate(${rotation}deg)`,
                transitionDuration: isBusy ? `${Math.max(2, Math.min(60, spinSeconds))}s` : "700ms",
              }}
            >
              {labelSegments.map((segment, index) => {
                const midAngle = (segment.start + segment.end) / 2
                const visualAngle = midAngle - 90
                const readableAngle = visualAngle > 90 && visualAngle < 270 ? visualAngle + 180 : visualAngle
                const angleRad = (visualAngle * Math.PI) / 180
                const radius = 31
                const left = 50 + Math.cos(angleRad) * radius
                const top = 50 + Math.sin(angleRad) * radius
                return (
                  <span
                    key={`${segment.login}-${index}-${segment.start}`}
                    className="absolute max-w-[150px] origin-center truncate text-sm font-semibold text-white drop-shadow-[0_2px_2px_rgba(0,0,0,0.9)]"
                    style={{
                      left: `${left}%`,
                      top: `${top}%`,
                      transform: `translate(-50%, -50%) rotate(${readableAngle + 45}deg)`,
                    }}
                  >
                    {segment.displayName}
                  </span>
                )
              })}
              <div className="absolute inset-[42%] rounded-full border-2 border-white/80 bg-background/20" />
            </div>
            <div className="pointer-events-none absolute inset-0 rounded-full bg-[radial-gradient(circle,transparent_58%,rgba(255,255,255,0.22)_100%)]" />
          </div>
          <div className="text-sm text-muted-foreground">
            Участников в колесе: {new Set(segments.map((segment) => segment.login)).size}
            {mode === "elimination" ? ` · выбыло: ${eliminatedLogins.length}` : ""}
            {lastSource ? ` · источник: ${lastSource}` : ""}
          </div>
        </div>

        <div className="space-y-4">
          <Button type="button" className="w-full" onClick={onSpin} disabled={isBusy || segments.length === 0}>
            {isBusy ? <Loader2 className="size-4 animate-spin" /> : <Trophy className="size-4" />}
            Крутить
          </Button>
          <label className="space-y-2">
            <span className="text-sm font-medium text-muted-foreground">Длительность прокрута</span>
            <div className="flex items-center gap-2">
              <Input min="2" max="60" type="number" value={spinSeconds} onChange={(event) => onSpinSecondsChange(Math.max(2, Math.min(60, Number.parseInt(event.target.value, 10) || 8)))} />
              <span className="text-sm text-muted-foreground">с.</span>
            </div>
          </label>
          <div className="grid grid-cols-2 rounded-lg border bg-card p-1">
            <button type="button" className={mode === "normal" ? "rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground" : "px-3 py-2 text-sm text-muted-foreground"} onClick={() => onModeChange("normal")}>Обычный</button>
            <button type="button" className={mode === "elimination" ? "rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground" : "px-3 py-2 text-sm text-muted-foreground"} onClick={() => onModeChange("elimination")}>Выбывание</button>
          </div>
          <label className="space-y-2">
            <span className="flex items-center justify-between gap-3 text-sm font-medium">
              <span>Разделение</span>
              <span className="text-muted-foreground">{split}/10</span>
            </span>
            <Input min="0" max="10" type="range" value={split} onChange={(event) => onSplitChange(Number.parseInt(event.target.value, 10))} />
            <span className="block text-xs text-muted-foreground">10: по одному слоту на человека. Ближе к 0: больше слотов, но общий шанс не меняется.</span>
          </label>
          <div className="rounded-lg border bg-card p-3 text-sm text-muted-foreground">
            Результат берётся с RANDOM.ORG. Размер доли участника соответствует его множителю в списке.
          </div>
        </div>
      </div>
      </div>
    </section>
  )
}

function GiveawayTypeButton({
  active,
  description,
  label,
  onClick,
}: {
  active: boolean
  description: string
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className={active ? "rounded-lg border border-primary bg-primary/10 p-4 text-left" : "rounded-lg border bg-background p-4 text-left hover:bg-accent"}
      onClick={onClick}
    >
      <span className="flex items-center gap-3">
        <span className={active ? "flex size-4 rounded-full border-4 border-primary" : "size-4 rounded-full border"} />
        <span className="font-medium">{label}</span>
      </span>
      <span className="mt-2 block text-sm text-muted-foreground">{description}</span>
    </button>
  )
}

function GiveawayRunButton({
  isBusy,
  isRunning,
  onClick,
}: {
  isBusy: boolean
  isRunning: boolean
  onClick: () => void
}) {
  return (
    <Button
      type="button"
      variant={isRunning ? "destructive" : "outline"}
      onClick={onClick}
      disabled={isBusy}
    >
      {isBusy ? <Loader2 className="size-4 animate-spin" /> : isRunning ? <Square className="size-4" /> : <Play className="size-4" />}
      {isRunning ? "Остановить" : "Запустить"}
    </Button>
  )
}

function TwitchChatPanel({
  channelLogin,
  externalUrl,
  loadState,
  mode,
  onLoad,
  onRetry,
  onUsePopout,
  reloadKey,
  src,
}: {
  channelLogin: string
  externalUrl: string
  loadState: "loading" | "loaded" | "timeout"
  mode: "embed" | "popout"
  onLoad: () => void
  onRetry: () => void
  onUsePopout: () => void
  reloadKey: number
  src: string
}) {
  return (
    <div className="relative h-[720px] min-h-[640px] w-full overflow-hidden bg-background xl:h-[calc(100vh-160px)]">
      <iframe
        key={`${mode}-${reloadKey}-${src}`}
        title={`Twitch chat ${channelLogin}`}
        src={src}
        className="h-full w-full border-0"
        allowFullScreen
        onLoad={onLoad}
      />
      {loadState === "timeout" ? (
        <div className="absolute inset-0 grid place-items-center bg-background/95 p-6 text-center backdrop-blur-sm">
          <div className="max-w-sm space-y-4">
            <div>
              <div className="text-lg font-semibold">Twitch не ответил</div>
              <div className="mt-1 text-sm text-muted-foreground">
                Встроенный чат канала @{channelLogin} не загрузился. Это может быть временный таймаут Twitch или блокировка iframe браузером.
              </div>
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:justify-center">
              <Button type="button" variant="outline" onClick={onRetry}>
                Повторить
              </Button>
              {mode === "embed" ? (
                <Button type="button" variant="outline" onClick={onUsePopout}>
                  Открыть popout
                </Button>
              ) : null}
              <Button asChild>
                <a href={externalUrl} target="_blank" rel="noreferrer">
                  Открыть отдельно
                </a>
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function getTwitchChatParents() {
  if (typeof window === "undefined") return ["localhost"]
  const hostname = window.location.hostname.trim().toLowerCase() || "localhost"
  const parents = [hostname]
  if (hostname.startsWith("www.")) {
    parents.push(hostname.slice(4))
  } else if (!["localhost", "127.0.0.1"].includes(hostname)) {
    parents.push(`www.${hostname}`)
  }
  return Array.from(new Set(parents))
}

function buildWheelSegments(participants: GiveawayState["participants"], eliminatedLogins: string[], mode: "normal" | "elimination", split: number): WheelSegment[] {
  const eliminated = new Set(eliminatedLogins)
  const activeParticipants = participants.filter((participant) => mode !== "elimination" || !eliminated.has(participant.login))
  const totalWeight = activeParticipants.reduce((sum, participant) => sum + Math.max(0, participant.multiplier), 0)
  if (!activeParticipants.length || totalWeight <= 0) return []
  const slotMultiplier = Math.max(1, 1 + Math.round((10 - split) * 2.5))
  const colors = ["#ef4444", "#f97316", "#facc15", "#22c55e", "#06b6d4", "#3b82f6", "#8b5cf6", "#ec4899"]
  let cursor = 0
  return activeParticipants.flatMap((participant, participantIndex) => {
    const slots = Math.max(1, slotMultiplier)
    const participantPercent = Math.max(0, participant.multiplier) / totalWeight
    const slotPercent = participantPercent / slots
    return Array.from({ length: slots }, (_, slotIndex) => {
      const start = cursor * 360
      cursor += slotPercent
      return {
        login: participant.login,
        displayName: participant.display_name,
        multiplier: participant.multiplier,
        percent: participantPercent * 100,
        color: colors[(participantIndex + slotIndex) % colors.length],
        start,
        end: cursor * 360,
      }
    })
  })
}

function getWheelTargetAngle(segments: WheelSegment[], login: string) {
  const segment = segments.find((item) => item.login === login)
  if (!segment) return 0
  return segment.start + (segment.end - segment.start) / 2
}

function MultiplierField({ label, onChange, value }: { label: string; onChange: (value: string) => void; value: number }) {
  return (
    <label className="space-y-2">
      <span className="text-sm font-medium text-muted-foreground">{label}</span>
      <div className="relative">
        <Input min="0" step="0.1" type="number" value={value} onChange={(event) => onChange(event.target.value)} />
        <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-muted-foreground">x</span>
      </div>
    </label>
  )
}
