import { CircleAlert, Loader2, RefreshCw, ShieldCheck, ShieldMinus, SlidersHorizontal, UserPlus, Users, type LucideIcon } from "lucide-react"
import { useEffect, useState, type ChangeEvent, type ReactNode } from "react"
import { Trash2, Upload, UserMinus } from "lucide-react"

import { PageHeader } from "@/components/app/page-header"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Toast, type ToastNotice } from "@/components/ui/toast"
import { useJsonQuery } from "@/hooks/use-json-query"
import { requestForm, requestJson } from "@/lib/api"
import type { MutationResult, SettingsPayload } from "@/types/app"

type RangeField = { min: string; max: string }

type GlobalSettingsForm = {
  autobet_require_stream_online: boolean
  quiz_passive_debug_allow_offline: boolean
  dota2_ranges: {
    kills: RangeField
    deaths: RangeField
    assists: RangeField
    duration: RangeField
  }
  cs2_ranges: {
    kills: RangeField
    deaths: RangeField
    assists: RangeField
  }
}

function toRangeField(value: { min: number; max: number }): RangeField {
  return {
    min: String(value.min),
    max: String(value.max),
  }
}

function buildGlobalSettingsForm(data: SettingsPayload): GlobalSettingsForm {
  return {
    autobet_require_stream_online: data.global_settings.autobet_require_stream_online,
    quiz_passive_debug_allow_offline: data.global_settings.quiz_passive_debug_allow_offline,
    dota2_ranges: {
      kills: toRangeField(data.global_settings.custom_market_ranges.dota2.kills),
      deaths: toRangeField(data.global_settings.custom_market_ranges.dota2.deaths),
      assists: toRangeField(data.global_settings.custom_market_ranges.dota2.assists),
      duration: toRangeField(data.global_settings.custom_market_ranges.dota2.duration),
    },
    cs2_ranges: {
      kills: toRangeField(data.global_settings.custom_market_ranges.cs2.kills),
      deaths: toRangeField(data.global_settings.custom_market_ranges.cs2.deaths),
      assists: toRangeField(data.global_settings.custom_market_ranges.cs2.assists),
    },
  }
}

export function AdminPage() {
  const { data, isLoading, error, refetch } = useJsonQuery<SettingsPayload>("/api/app/settings")
  const [notice, setNotice] = useState<ToastNotice | null>(null)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [presetUploadName, setPresetUploadName] = useState("")
  const [presetUploadFile, setPresetUploadFile] = useState<File | null>(null)
  const [presetUploadInputKey, setPresetUploadInputKey] = useState(0)
  const [globalForm, setGlobalForm] = useState<GlobalSettingsForm | null>(null)
  const [debugChannelQuery, setDebugChannelQuery] = useState("")
  const [selectedDebugChannelId, setSelectedDebugChannelId] = useState<number | null>(null)
  const [debugPickerOpen, setDebugPickerOpen] = useState(false)

  useEffect(() => {
    if (!data) return
    if (busyAction === "global-settings") return
    setGlobalForm(buildGlobalSettingsForm(data))
  }, [busyAction, data])

  useEffect(() => {
    if (!data?.autobet_debug_channels.length) {
      setSelectedDebugChannelId(null)
      return
    }
    setSelectedDebugChannelId((current) => {
      if (current && data.autobet_debug_channels.some((channel) => channel.id === current)) {
        return current
      }
      return null
    })
  }, [data])

  async function mutateAdmin(action: "grant" | "revoke", userId: number) {
    const label = `${action}-${userId}`
    setBusyAction(label)
    setNotice(null)

    try {
      await requestJson<MutationResult>(`/api/app/settings/admins/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId }),
      })
      await refetch()
      setNotice(
        action === "grant"
          ? { type: "success", title: "Администратор добавлен", text: "Доступ к админке обновлён." }
          : { type: "warning", title: "Админка снята", text: "Пользователь больше не видит служебные разделы." },
      )
    } catch (caughtError) {
      setNotice({
        type: "error",
        title: action === "grant" ? "Не удалось выдать админку" : "Не удалось снять админку",
        text: (caughtError as Error).message,
      })
    } finally {
      setBusyAction(null)
    }
  }

  async function saveGlobalSettings() {
    if (!globalForm) return
    setBusyAction("global-settings")
    setNotice(null)
    try {
      await requestJson<MutationResult>("/api/app/settings/global", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(globalForm),
      })
      await refetch()
      setNotice({ type: "success", title: "Настройки сохранены", text: "Правила автоставок и диапазоны обновлены." })
    } catch (caughtError) {
      setNotice({ type: "error", title: "Не удалось сохранить", text: (caughtError as Error).message })
    } finally {
      setBusyAction(null)
    }
  }

  async function distributeQuestionPreset(fileName: string, presetName: string) {
    setBusyAction(`question-preset-access-${fileName}`)
    setNotice(null)
    try {
      const result = await requestJson<
        MutationResult & {
          added?: number
          skipped_existing?: number
          skipped_limit?: number
          failed?: number
        }
      >("/api/app/settings/question-presets/distribute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_name: fileName }),
      })
      await refetch()
      setNotice({
        type: result.failed ? "warning" : "success",
        title: `Пресет «${presetName}» раздан`,
        text:
          result.message ??
          `Добавлено: ${result.added ?? 0}. Уже был: ${result.skipped_existing ?? 0}. Пропущено по лимиту: ${result.skipped_limit ?? 0}.`,
      })
    } catch (caughtError) {
      setNotice({ type: "error", title: "Не удалось раздать пресет", text: (caughtError as Error).message })
    } finally {
      setBusyAction(null)
    }
  }

  function handlePresetFileChange(event: ChangeEvent<HTMLInputElement>) {
    setPresetUploadFile(event.target.files?.[0] ?? null)
  }

  async function uploadQuestionPreset() {
    if (!presetUploadFile) {
      setNotice({ type: "error", title: "Файл не выбран", text: "Выбери JSON-файл со стандартным паком вопросов." })
      return
    }
    setBusyAction("question-preset-upload")
    setNotice(null)
    try {
      const formData = new FormData()
      formData.set("config_name", presetUploadName)
      formData.set("questions_file", presetUploadFile)
      await requestForm<MutationResult>("/api/app/settings/question-presets/upload", formData)
      setPresetUploadName("")
      setPresetUploadFile(null)
      setPresetUploadInputKey((current) => current + 1)
      await refetch()
      setNotice({ type: "success", title: "Пак загружен", text: "Новый стандартный конфиг появился в общем списке." })
    } catch (caughtError) {
      setNotice({ type: "error", title: "Не удалось загрузить пак", text: (caughtError as Error).message })
    } finally {
      setBusyAction(null)
    }
  }

  async function deleteQuestionPreset(fileName: string, presetName: string) {
    if (!window.confirm(`Полностью удалить пак «${presetName}»: убрать у всех каналов и стереть его из админки?`)) return
    setBusyAction(`question-preset-delete-${fileName}`)
    setNotice(null)
    try {
      const result = await requestJson<MutationResult & { deleted_links?: number; message?: string }>(
        "/api/app/settings/question-presets/delete",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file_name: fileName }),
        },
      )
      await refetch()
      setNotice({
        type: "warning",
        title: `Пак «${presetName}» удалён полностью`,
        text: result.message ?? `Отвязано у каналов: ${result.deleted_links ?? 0}.`,
      })
    } catch (caughtError) {
      setNotice({ type: "error", title: "Не удалось удалить пак", text: (caughtError as Error).message })
    } finally {
      setBusyAction(null)
    }
  }

  async function revokeQuestionPreset(fileName: string, presetName: string) {
    if (!window.confirm(`Убрать пак «${presetName}» из общего доступа у всех каналов, но оставить его в админке?`)) return
    setBusyAction(`question-preset-access-${fileName}`)
    setNotice(null)
    try {
      const result = await requestJson<MutationResult & { deleted_links?: number; message?: string }>(
        "/api/app/settings/question-presets/revoke",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file_name: fileName }),
        },
      )
      await refetch()
      setNotice({
        type: "warning",
        title: `Пак «${presetName}» убран из общего доступа`,
        text: result.message ?? `Убрано у каналов: ${result.deleted_links ?? 0}.`,
      })
    } catch (caughtError) {
      setNotice({ type: "error", title: "Не удалось убрать пак из общего доступа", text: (caughtError as Error).message })
    } finally {
      setBusyAction(null)
    }
  }

  async function toggleQuestionPresetAccess(fileName: string, presetName: string, linkedUserCount: number) {
    if (linkedUserCount > 0) {
      await revokeQuestionPreset(fileName, presetName)
      return
    }
    await distributeQuestionPreset(fileName, presetName)
  }

  function updateRange(game: "dota2" | "cs2", market: string, side: "min" | "max", value: string) {
    setGlobalForm((current) => {
      if (!current) return current
      const rangesKey = game === "dota2" ? "dota2_ranges" : "cs2_ranges"
      const gameRanges = current[rangesKey] as Record<string, RangeField>
      return {
        ...current,
        [rangesKey]: {
          ...gameRanges,
          [market]: {
            ...(gameRanges[market] || { min: "", max: "" }),
            [side]: value,
          },
        },
      } as GlobalSettingsForm
    })
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-16 w-72" />
        <div className="grid gap-4 md:grid-cols-3">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
        <Skeleton className="h-96 w-full" />
      </div>
    )
  }

  if (error || !data || !globalForm) {
    return (
      <Alert variant="destructive">
        <CircleAlert className="mb-3 size-5" />
        <AlertTitle>Админка не загрузилась</AlertTitle>
        <AlertDescription>{error ?? "Сервер вернул пустой ответ."}</AlertDescription>
      </Alert>
    )
  }

  const normalizedDebugQuery = debugChannelQuery.trim().toLowerCase()
  const filteredDebugChannels = data.autobet_debug_channels.filter((channel) => {
    if (!normalizedDebugQuery) return false
    const haystacks = [channel.display_name, channel.login].map((value) => String(value || "").toLowerCase())
    return haystacks.some((value) => value.includes(normalizedDebugQuery))
  })
  const selectedDebugChannel =
    data.autobet_debug_channels.find((channel) => channel.id === selectedDebugChannelId) ??
    null

  function selectDebugChannel(channel: SettingsPayload["autobet_debug_channels"][number]) {
    setSelectedDebugChannelId(channel.id)
    setDebugChannelQuery(channel.display_name || channel.login)
    setDebugPickerOpen(false)
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <PageHeader title="Админ-панель" description={`Служебные настройки. Обновлено ${data.settings_updated_at}.`} />
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" onClick={() => void refetch()} disabled={busyAction !== null}>
            <RefreshCw className="size-4" />
            Обновить
          </Button>
          <Button type="button" onClick={() => void saveGlobalSettings()} disabled={busyAction !== null}>
            {busyAction === "global-settings" ? <Loader2 className="size-4 animate-spin" /> : <SlidersHorizontal className="size-4" />}
            Сохранить автоставки
          </Button>
        </div>
      </div>

      <Toast notice={notice} onClose={() => setNotice(null)} />

      <div className="grid gap-4 md:grid-cols-3">
        <AdminMetric icon={ShieldCheck} label="Администраторы" value={data.admin_users.length} />
        <AdminMetric icon={Users} label="Кандидаты" value={data.admin_candidates.length} />
        <AdminMetric icon={UserPlus} label="Текущий доступ" value={data.current_user_is_admin ? "Активен" : "Нет"} />
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle>Сервис</CardTitle>
              <CardDescription>Короткий health-срез по чату, тикам и внешним API.</CardDescription>
            </div>
            <Badge variant={metricsBadgeVariant(data.service_metrics.health.status)}>{data.service_metrics.health.label}</Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {data.service_metrics.overview_cards.map((item) => (
              <div key={item.label} className="rounded-lg border p-4">
                <div className="text-sm text-muted-foreground">{item.label}</div>
                <div className="mt-2 text-2xl font-semibold">{item.value}</div>
                <div className="mt-1 text-sm text-muted-foreground">{item.description}</div>
              </div>
            ))}
          </div>

          <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
            <div className="space-y-3">
              <div className="text-sm font-medium">Контуры</div>
              <div className="divide-y rounded-lg border">
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
              <div className="text-sm font-medium">Свежие ошибки</div>
              <div className="divide-y rounded-lg border">
                {data.service_metrics.recent_errors.length ? (
                  data.service_metrics.recent_errors.slice(0, 6).map((item) => (
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

      <Card>
        <CardHeader>
          <CardTitle>Автоставки</CardTitle>
          <CardDescription>Здесь задаются глобальные правила открытия ставок и диапазоны для кастомных рынков.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="flex items-center justify-between gap-4 rounded-lg border p-4">
            <div className="min-w-0">
              <div className="font-medium">Создавать ставки только когда стрим онлайн</div>
              <div className="mt-1 text-sm text-muted-foreground">Отключай для тестов без трансляции. В боевом режиме лучше держать включённым.</div>
            </div>
            <Switch
              checked={globalForm.autobet_require_stream_online}
              disabled={busyAction === "global-settings"}
              onCheckedChange={(checked) => setGlobalForm((current) => (current ? { ...current, autobet_require_stream_online: checked } : current))}
            />
          </div>

          <div className="flex items-center justify-between gap-4 rounded-lg border p-4">
            <div className="min-w-0">
              <div className="font-medium">{"\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u043f\u0430\u0441\u0441\u0438\u0432\u043d\u043e\u0439 \u0432\u0438\u043a\u0442\u043e\u0440\u0438\u043d\u044b \u0431\u0435\u0437 \u044d\u0444\u0438\u0440\u0430"}</div>
              <div className="mt-1 text-sm text-muted-foreground">{"\u0415\u0441\u043b\u0438 \u0432\u043a\u043b\u044e\u0447\u0435\u043d\u043e, \u0441\u043b\u0443\u0447\u0430\u0439\u043d\u044b\u0435 \u0432\u043e\u043f\u0440\u043e\u0441\u044b \u043c\u043e\u0433\u0443\u0442 \u043f\u043e\u044f\u0432\u043b\u044f\u0442\u044c\u0441\u044f \u0434\u0430\u0436\u0435 \u043a\u043e\u0433\u0434\u0430 \u0441\u0442\u0440\u0438\u043c \u043e\u0444\u043b\u0430\u0439\u043d. \u0415\u0441\u043b\u0438 \u0432\u044b\u043a\u043b\u044e\u0447\u0435\u043d\u043e, \u043f\u0430\u0441\u0441\u0438\u0432\u043d\u044b\u0439 \u0440\u0435\u0436\u0438\u043c \u0436\u0434\u0451\u0442 \u0436\u0438\u0432\u043e\u0439 \u044d\u0444\u0438\u0440."}</div>
            </div>
            <Switch
              checked={globalForm.quiz_passive_debug_allow_offline}
              disabled={busyAction === "global-settings"}
              onCheckedChange={(checked) =>
                setGlobalForm((current) => (current ? { ...current, quiz_passive_debug_allow_offline: checked } : current))
              }
            />
          </div>

          <div className="grid gap-6 xl:grid-cols-2">
            <RangeSection
              title="Dota 2"
              description="Диапазоны работают для всех числовых рынков Dota 2 в текущем GSI-only режиме: киллы, смерти, ассисты и длительность."
              rows={[
                { key: "kills", label: "Киллы", value: globalForm.dota2_ranges.kills },
                { key: "deaths", label: "Смерти", value: globalForm.dota2_ranges.deaths },
                { key: "assists", label: "Ассисты", value: globalForm.dota2_ranges.assists },
                { key: "duration", label: "Длительность, мин", value: globalForm.dota2_ranges.duration },
              ]}
              onChange={(market, side, value) => updateRange("dota2", market, side, value)}
            />

            <RangeSection
              title="CS2"
              description='Для киллов, смертей и ассистов бот берёт число только внутри этого коридора и формулирует ставку как "больше X".'
              rows={[
                { key: "kills", label: "Киллы", value: globalForm.cs2_ranges.kills },
                { key: "deaths", label: "Смерти", value: globalForm.cs2_ranges.deaths },
                { key: "assists", label: "Ассисты", value: globalForm.cs2_ranges.assists },
              ]}
              onChange={(market, side, value) => updateRange("cs2", market, side, value)}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Стандартные конфиги вопросов</CardTitle>
          <CardDescription>Загружай общие паки, раздавай их всем каналам и управляй ими из одного места. Пользователи могут выбирать такие паки, но не удалять их у себя.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid gap-3 rounded-lg border p-4 md:grid-cols-[minmax(0,1fr)_220px_auto]">
            <Input
              value={presetUploadName}
              placeholder="Название нового пака"
              onChange={(event) => setPresetUploadName(event.target.value)}
            />
            <Input
              key={presetUploadInputKey}
              type="file"
              accept=".json,application/json"
              onChange={handlePresetFileChange}
            />
            <Button type="button" onClick={() => void uploadQuestionPreset()} disabled={busyAction !== null}>
              {busyAction === "question-preset-upload" ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
              Загрузить пак
            </Button>
          </div>

          {data.standard_question_presets.length ? (
            data.standard_question_presets.map((preset) => {
              const accessBusy = busyAction === `question-preset-access-${preset.file_name}`
              const deleting = busyAction === `question-preset-delete-${preset.file_name}`
              return (
                  <div key={preset.file_name} className="flex flex-col gap-3 rounded-lg border p-4 md:flex-row md:items-center md:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2 font-medium">
                        <span>{preset.name}</span>
                        <Badge variant="outline">Админский пак</Badge>
                        <Badge variant="outline">{preset.is_builtin ? "Встроенный" : "Загруженный"}</Badge>
                        <Badge variant="outline">{preset.preset_id}</Badge>
                      </div>
                      <div className="mt-1 text-sm text-muted-foreground">
                        {preset.question_count} вопросов • выдан каналам: {preset.linked_user_count}
                      </div>
                    </div>
                    <div className="grid gap-2 md:grid-cols-3">
                      <Button
                        type="button"
                        variant={preset.linked_user_count > 0 ? "outline" : "default"}
                        onClick={() => void toggleQuestionPresetAccess(preset.file_name, preset.name, preset.linked_user_count)}
                        disabled={busyAction !== null}
                        className="w-full"
                      >
                        {accessBusy ? (
                          <Loader2 className="size-4 animate-spin" />
                        ) : preset.linked_user_count > 0 ? (
                          <UserMinus className="size-4" />
                        ) : (
                          <UserPlus className="size-4" />
                        )}
                        {preset.linked_user_count > 0 ? "Забрать у всех" : "Выдать всем"}
                      </Button>
                      <div className="hidden md:block" />
                      <Button type="button" variant="outline" onClick={() => void deleteQuestionPreset(preset.file_name, preset.name)} disabled={busyAction !== null} className="w-full">
                        {deleting ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                        Удалить полностью
                      </Button>
                    </div>
                  </div>
                )
              })
          ) : (
            <div className="rounded-lg border border-dashed bg-muted/30 p-6 text-sm text-muted-foreground">Стандартных паков пока нет.</div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>GSI debug по каналам</CardTitle>
          <CardDescription>Живой срез для автоставок: что реально прилетает из игры и пройдёт ли автооткрытие прямо сейчас.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {data.autobet_debug_channels.length ? (
            <div className="space-y-4">
              <div className="relative w-full">
                <Input
                  value={debugChannelQuery}
                  placeholder="Начни вводить канал"
                  onFocus={() => setDebugPickerOpen(true)}
                  onBlur={() => window.setTimeout(() => setDebugPickerOpen(false), 120)}
                  onChange={(event) => {
                    setDebugChannelQuery(event.target.value)
                    setDebugPickerOpen(true)
                  }}
                />
                {debugPickerOpen && normalizedDebugQuery ? (
                  <div className="absolute z-20 mt-2 max-h-72 w-full overflow-auto rounded-lg border bg-background shadow-xl">
                    {filteredDebugChannels.length ? (
                      filteredDebugChannels.slice(0, 8).map((channel) => (
                        <button
                          key={channel.id}
                          type="button"
                          className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-muted/60"
                          onMouseDown={(event) => {
                            event.preventDefault()
                            selectDebugChannel(channel)
                          }}
                        >
                          <div className="min-w-0">
                            <div className="font-medium">{channel.display_name}</div>
                            <div className="text-sm text-muted-foreground">@{channel.login}</div>
                          </div>
                          <div className="flex shrink-0 gap-2">
                            <Badge variant={channel.dota2_enabled ? "success" : "outline"}>Dota</Badge>
                            <Badge variant={channel.cs2_enabled ? "success" : "outline"}>CS2</Badge>
                          </div>
                        </button>
                      ))
                    ) : (
                      <div className="px-4 py-3 text-sm text-muted-foreground">Похожих каналов не найдено.</div>
                    )}
                  </div>
                ) : null}
              </div>

              {selectedDebugChannel ? (
                <div className="rounded-lg border p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="font-medium">{selectedDebugChannel.display_name}</div>
                      <div className="text-sm text-muted-foreground">@{selectedDebugChannel.login}</div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <Badge variant={selectedDebugChannel.dota2_enabled ? "success" : "outline"}>Dota {selectedDebugChannel.dota2_enabled ? "on" : "off"}</Badge>
                        <Badge variant={selectedDebugChannel.cs2_enabled ? "success" : "outline"}>CS2 {selectedDebugChannel.cs2_enabled ? "on" : "off"}</Badge>
                        {selectedDebugChannel.active_prediction_id ? (
                          <Badge variant="outline">Активная ставка: {selectedDebugChannel.active_game_key || "twitch"}</Badge>
                        ) : (
                          <Badge variant="outline">Ставки свободны</Badge>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="mt-4 space-y-4">
                    <GameDebugPane title="Dota 2" game={selectedDebugChannel.gsi.dota2} />
                    <GameDebugPane title="CS2" game={selectedDebugChannel.gsi.cs2} />
                  </div>
                </div>
              ) : (
                <div className="rounded-lg border border-dashed bg-muted/30 p-6 text-sm text-muted-foreground">Начни вводить название канала и выбери его из списка.</div>
              )}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed bg-muted/30 p-6 text-sm text-muted-foreground">Подключённых каналов для debug-среза пока нет.</div>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="size-5" />
              Текущие администраторы
            </CardTitle>
            <CardDescription>Здесь можно забрать доступ у уже назначенных администраторов.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {data.admin_users.map((admin) => {
              const isCurrentUser = admin.id === data.user.id
              const busy = busyAction === `revoke-${admin.id}`
              return (
                <UserRow
                  key={admin.id}
                  displayName={admin.display_name}
                  login={admin.login}
                  createdAt={admin.created_at_formatted}
                  updatedAt={admin.updated_at_formatted}
                  badge={isCurrentUser ? <Badge variant="outline">Это ты</Badge> : <Badge variant="success">Администратор</Badge>}
                  action={
                    <Button type="button" variant="destructive" onClick={() => void mutateAdmin("revoke", admin.id)} disabled={busy || isCurrentUser}>
                      {busy ? <Loader2 className="size-4 animate-spin" /> : <ShieldMinus className="size-4" />}
                      Снять админку
                    </Button>
                  }
                />
              )
            })}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Users className="size-5" />
              Кандидаты
            </CardTitle>
            <CardDescription>Пользователи, которые уже входили в кабинет через Twitch.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {data.admin_candidates.length ? (
              data.admin_candidates.map((candidate) => {
                const busy = busyAction === `grant-${candidate.id}`
                return (
                  <UserRow
                    key={candidate.id}
                    displayName={candidate.display_name}
                    login={candidate.login}
                    createdAt={candidate.created_at_formatted}
                    updatedAt={candidate.updated_at_formatted}
                    badge={<Badge variant="outline">Кандидат</Badge>}
                    action={
                      <Button type="button" onClick={() => void mutateAdmin("grant", candidate.id)} disabled={busy}>
                        {busy ? <Loader2 className="size-4 animate-spin" /> : <UserPlus className="size-4" />}
                        Выдать админку
                      </Button>
                    }
                  />
                )
              })
            ) : (
              <div className="rounded-lg border border-dashed bg-muted/30 p-6 text-sm text-muted-foreground">Новых кандидатов пока нет.</div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function AdminMetric({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: number | string }) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4 p-4">
        <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-secondary text-secondary-foreground">
          <Icon className="size-5" />
        </div>
        <div>
          <div className="text-sm text-muted-foreground">{label}</div>
          <div className="text-2xl font-semibold">{value}</div>
        </div>
      </CardContent>
    </Card>
  )
}

function metricsBadgeVariant(status: "healthy" | "warning" | "error"): "success" | "outline" | "destructive" {
  if (status === "healthy") return "success"
  if (status === "error") return "destructive"
  return "outline"
}

function RangeSection({
  title,
  description,
  rows,
  onChange,
}: {
  title: string
  description: string
  rows: Array<{ key: string; label: string; value: RangeField }>
  onChange: (market: string, side: "min" | "max", value: string) => void
}) {
  return (
    <div className="space-y-4 rounded-lg border p-4">
      <div>
        <div className="font-medium">{title}</div>
        <div className="mt-1 text-sm text-muted-foreground">{description}</div>
      </div>
      <div className="divide-y">
        {rows.map((row) => (
          <div key={row.key} className="grid gap-3 py-3 md:grid-cols-[minmax(0,1fr)_120px_120px] md:items-center">
            <div className="font-medium">{row.label}</div>
            <Input value={row.value.min} inputMode="numeric" placeholder="От" onChange={(event) => onChange(row.key, "min", event.target.value)} />
            <Input value={row.value.max} inputMode="numeric" placeholder="До" onChange={(event) => onChange(row.key, "max", event.target.value)} />
          </div>
        ))}
      </div>
    </div>
  )
}

function GameDebugPane({
  title,
  game,
}: {
  title: string
  game: SettingsPayload["autobet_debug_channels"][number]["gsi"]["dota2"]
}) {
  return (
    <div className="rounded-lg border bg-muted/20 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-medium">{title}</div>
        <div className="flex flex-wrap gap-2">
          <Badge variant={game.connected ? "success" : "outline"}>{game.connected ? "Подключено" : "Нет сигнала"}</Badge>
          <Badge variant={game.opening_allowed ? "success" : "outline"}>{game.opening_allowed ? "Откроется" : "Ждёт"}</Badge>
        </div>
      </div>
      <div className="mt-3 space-y-2 text-sm">
        <DebugRow label="Последний сигнал" value={game.last_seen_label} />
        <DebugRow label="Match id" value={game.match_id || "—"} />
        <DebugRow label="Состояние" value={game.game_state || "—"} />
        <DebugRow label="Субъект" value={game.subject_label || "—"} />
        <DebugRow label="Счёт" value={game.score_line} />
        <DebugRow label="Режим" value={game.mode_label || "—"} />
        {game.game_time > 0 ? <DebugRow label="Время" value={String(game.game_time)} /> : null}
        {game.extra_label ? <DebugRow label="Команда" value={game.extra_label} /> : null}
        {game.block_reason ? <DebugRow label="Почему не откроется" value={game.block_reason} muted /> : null}
        {game.last_error ? <DebugRow label="Последняя ошибка" value={game.last_error} muted /> : null}
      </div>
    </div>
  )
}

function DebugRow({ label, value, muted = false }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className="grid grid-cols-[110px_minmax(0,1fr)] gap-3">
      <div className="text-muted-foreground">{label}</div>
      <div className={muted ? "text-muted-foreground" : "font-medium"}>{value}</div>
    </div>
  )
}

function UserRow({
  action,
  badge,
  createdAt,
  displayName,
  login,
  updatedAt,
}: {
  action?: ReactNode
  badge?: ReactNode
  createdAt: string
  displayName: string
  login: string
  updatedAt: string
}) {
  return (
    <div className="rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <div className="font-medium">{displayName}</div>
            {badge}
          </div>
          <div className="text-sm text-muted-foreground">@{login}</div>
          <div className="mt-2 text-xs text-muted-foreground">
            Подключён: {createdAt} · Обновлён: {updatedAt}
          </div>
        </div>
        {action}
      </div>
    </div>
  )
}
