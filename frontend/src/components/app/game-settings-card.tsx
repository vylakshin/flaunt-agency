import {
  CheckCircle2,
  CircleAlert,
  Loader2,
  MessageSquareText,
  Settings2,
  ShieldCheck,
  Users,
  type LucideIcon,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import { Switch } from "@/components/ui/switch"
import { cn } from "@/lib/utils"
import type { DashboardPayload } from "@/types/app"

export type DashboardSettingsForm = {
  answer_cooldown_seconds: string
  command_access: string
  overlay_theme: string
  turbo_mode: boolean
  quiz_passive_mode: boolean
  quiet_mode: boolean
  chat_questions_enabled: boolean
  chat_outcomes_enabled: boolean
}

export type SettingsSaveState = "idle" | "saving" | "saved" | "error"

const commandDescriptions: Record<string, string> = {
  owner: "Команды доступны только владельцу канала.",
  moderators: "Владелец и модераторы могут управлять игрой.",
  everyone: "Открытый режим, где чат может запускать команды бота.",
}

export function serializeDashboardSettings(settings: DashboardSettingsForm) {
  return JSON.stringify({
    answer_cooldown_seconds: settings.answer_cooldown_seconds,
    command_access: settings.command_access,
    overlay_theme: settings.overlay_theme,
    turbo_mode: settings.turbo_mode,
    quiz_passive_mode: settings.quiz_passive_mode,
    quiet_mode: settings.quiet_mode,
    chat_questions_enabled: settings.chat_questions_enabled,
    chat_outcomes_enabled: settings.chat_outcomes_enabled,
  })
}

export function dashboardSettingsFromPayload(data: DashboardPayload): DashboardSettingsForm {
  return {
    answer_cooldown_seconds: String(data.settings.answer_cooldown_seconds),
    command_access: data.settings.command_access,
    overlay_theme: data.settings.overlay_theme,
    turbo_mode: data.settings.turbo_mode,
    quiz_passive_mode: data.settings.quiz_passive_mode,
    quiet_mode: data.settings.quiet_mode,
    chat_questions_enabled: data.settings.chat_questions_enabled,
    chat_outcomes_enabled: data.settings.chat_outcomes_enabled,
  }
}

export function syncDashboardSettingsChatMode(nextState: DashboardSettingsForm): DashboardSettingsForm {
  const next = { ...nextState }
  if (next.quiet_mode) {
    next.chat_questions_enabled = false
    next.chat_outcomes_enabled = false
  } else if (next.chat_questions_enabled || next.chat_outcomes_enabled) {
    next.quiet_mode = false
  } else {
    next.quiet_mode = true
  }
  return next
}

export function GameSettingsCard({
  formState,
  data,
  isSaving,
  settingsSaveState,
  updateSettings,
}: {
  formState: DashboardSettingsForm
  data: DashboardPayload
  isSaving: boolean
  settingsSaveState: SettingsSaveState
  updateSettings: (next: Partial<DashboardSettingsForm>) => void
}) {
  const selectedOverlayTheme = data.options.overlay_theme.find((theme) => theme.value === formState.overlay_theme) ?? data.options.overlay_theme[0] ?? null
  const selectedCommandAccess = data.options.command_access.find((option) => option.value === formState.command_access) ?? data.options.command_access[0] ?? null

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Settings2 className="size-5" />
          Настройки игры
        </CardTitle>
        <CardDescription>Темп игры, поведение в чате, доступ к командам и стиль overlay.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-8">
        <section className="space-y-4">
          <SectionCopy title="Темп игры" description="Кулдаун ответов ограничивает спам, а турбо меняет длительность раунда." />
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="answer-cooldown">КД между ответами</Label>
              <div className="relative">
                <Input
                  id="answer-cooldown"
                  inputMode="decimal"
                  min="0"
                  max="30"
                  step="0.5"
                  type="number"
                  value={formState.answer_cooldown_seconds}
                  onChange={(event) => updateSettings({ answer_cooldown_seconds: event.target.value })}
                />
                <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-muted-foreground">сек</span>
              </div>
            </div>
            <SwitchRow
              checked={formState.turbo_mode}
              description="30 секунд на раунд, буквы открываются каждые 5 секунд."
              label="Турбо режим"
              onCheckedChange={(checked) => updateSettings({ turbo_mode: checked })}
            />
            <SwitchRow
              checked={formState.quiz_passive_mode}
              description={"Вопросы не идут потоком: новый раунд появляется изредка в случайное время."}
              label={"Пассивный режим"}
              onCheckedChange={(checked) => updateSettings({ quiz_passive_mode: checked })}
            />
          </div>
        </section>

        <Separator />

        <section className="space-y-4">
          <SectionCopy title="Поведение в чате" description="Тихий режим выключает дополнительные сообщения, а чат-опции выключают тихий режим." />
          <div className="grid gap-3 md:grid-cols-3">
            <SwitchRow checked={formState.quiet_mode} description="Бот не дублирует игровые сообщения в чат." label="Тихий режим" onCheckedChange={(checked) => updateSettings({ quiet_mode: checked })} />
            <SwitchRow checked={formState.chat_questions_enabled} description="Категория, подсказка и маска слова при старте раунда." label="Дублировать вопросы" onCheckedChange={(checked) => updateSettings({ chat_questions_enabled: checked, quiet_mode: false })} />
            <SwitchRow checked={formState.chat_outcomes_enabled} description="Победитель, правильный ответ и результат раунда." label="Показывать ответ" onCheckedChange={(checked) => updateSettings({ chat_outcomes_enabled: checked, quiet_mode: false })} />
          </div>
        </section>

        <Separator />

        <section className="space-y-4">
          <SectionCopy title="Доступ к командам" description="Единая shadcn choice group вместо разных стилей старых свитчей." />
          <div className="grid gap-3 md:grid-cols-3">
            {data.options.command_access.map((option) => (
              <ChoiceCard
                key={option.value}
                active={formState.command_access === option.value}
                description={commandDescriptions[option.value] ?? "Настройка доступа к командам."}
                icon={option.value === "owner" ? ShieldCheck : option.value === "moderators" ? Users : MessageSquareText}
                label={option.label}
                onClick={() => updateSettings({ command_access: option.value })}
              />
            ))}
          </div>
        </section>

        <Separator />

        <section className="space-y-4">
          <SectionCopy title="Дизайн overlay" description={selectedOverlayTheme ? `Сейчас выбран: ${selectedOverlayTheme.label}.` : "Выбери стиль overlay для OBS."} />
          <div className="grid gap-3 lg:grid-cols-2">
            {data.options.overlay_theme.map((theme) => (
              <OverlayThemeCard
                key={theme.value}
                active={formState.overlay_theme === theme.value}
                description={theme.description}
                label={theme.label}
                overlayUrl={data.overlay_url}
                theme={theme.value}
                onClick={() => updateSettings({ overlay_theme: theme.value })}
              />
            ))}
          </div>
        </section>
      </CardContent>
      <div className="flex flex-col gap-2 border-t p-6 pt-4 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
        <div>
          Команды: <span className="font-medium text-foreground">{selectedCommandAccess?.label ?? formState.command_access}</span>
        </div>
        <SaveStatus state={settingsSaveState} isBusy={isSaving} />
      </div>
    </Card>
  )
}

function SectionCopy({ description, title }: { description: string; title: string }) {
  return (
    <div>
      <h3 className="font-medium">{title}</h3>
      <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{description}</p>
    </div>
  )
}

function SaveStatus({ isBusy, state }: { isBusy: boolean; state: SettingsSaveState }) {
  if (isBusy || state === "saving") {
    return (
      <span className="inline-flex items-center gap-2 text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        Автосохранение...
      </span>
    )
  }

  if (state === "error") {
    return (
      <span className="inline-flex items-center gap-2 text-destructive">
        <CircleAlert className="size-4" />
        Не сохранено
      </span>
    )
  }

  if (state === "saved") {
    return (
      <span className="inline-flex items-center gap-2 text-emerald-600 dark:text-emerald-400">
        <CheckCircle2 className="size-4" />
        Сохранено автоматически
      </span>
    )
  }

  return <span>Настройки применяются автоматически</span>
}

function SwitchRow({
  checked,
  description,
  label,
  onCheckedChange,
}: {
  checked: boolean
  description: string
  label: string
  onCheckedChange: (checked: boolean) => void
}) {
  return (
    <div className="grid min-h-28 grid-cols-[minmax(0,1fr)_auto] items-start gap-3 rounded-xl border bg-card p-4">
      <div className="min-w-0">
        <div className="font-medium">{label}</div>
        <div className="mt-1 text-sm leading-relaxed text-muted-foreground">{description}</div>
      </div>
      <Switch className="shrink-0" checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  )
}

function ChoiceCard({
  active,
  description,
  icon: Icon,
  label,
  onClick,
}: {
  active: boolean
  description: string
  icon: LucideIcon
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className={cn("rounded-xl border bg-card p-4 text-left transition hover:bg-accent/60", active && "border-primary bg-accent shadow-sm")}
      onClick={onClick}
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex size-10 items-center justify-center rounded-lg bg-secondary">
          <Icon className="size-4" />
        </div>
        {active ? <CheckCircle2 className="size-4 text-emerald-500" /> : null}
      </div>
      <div className="font-medium">{label}</div>
      <div className="mt-1 text-sm leading-relaxed text-muted-foreground">{description}</div>
    </button>
  )
}

function OverlayThemeCard({
  active,
  description,
  label,
  onClick,
  overlayUrl,
  theme,
}: {
  active: boolean
  description: string
  label: string
  onClick: () => void
  overlayUrl: string
  theme: string
}) {
  return (
    <button
      type="button"
      className={cn("overflow-hidden rounded-xl border bg-card text-left transition hover:bg-accent/60", active && "border-primary bg-accent shadow-sm")}
      onClick={onClick}
    >
      <ThemePreview overlayUrl={overlayUrl} theme={theme} />
      <div className="p-4">
        <div className="flex items-center justify-between gap-3">
          <div className="font-medium">{label}</div>
          {active ? <Badge variant="success">Активна</Badge> : <Badge variant="outline">Выбрать</Badge>}
        </div>
        <div className="mt-1 text-sm leading-relaxed text-muted-foreground">{description}</div>
      </div>
    </button>
  )
}

function ThemePreview({ overlayUrl, theme }: { overlayUrl: string; theme: string }) {
  const previewUrl = `${overlayUrl}${overlayUrl.includes("?") ? "&" : "?"}preview=1&preview_theme=${encodeURIComponent(theme)}`

  return (
    <div className="relative h-64 overflow-hidden border-b bg-slate-950">
      <iframe
        className="pointer-events-none absolute left-1/2 top-1/2 h-[800px] w-[520px] origin-center -translate-x-1/2 -translate-y-1/2 scale-[0.32] border-0"
        loading="lazy"
        src={previewUrl}
        title={`Overlay preview ${theme}`}
      />
    </div>
  )
}
