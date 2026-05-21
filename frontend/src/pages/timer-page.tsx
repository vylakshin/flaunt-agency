import { CheckCircle2, Clock3, MessageSquareText, Pencil, Plus, Search, Trash2, X } from "lucide-react"
import { useEffect, useState, type FormEvent, type ReactNode } from "react"

import { PageHeader } from "@/components/app/page-header"
import { PageShell } from "@/components/app/page-shell"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { showNotice } from "@/lib/notify"
import { useJsonQuery } from "@/hooks/use-json-query"
import { requestJson } from "@/lib/api"
import type { MutationResult, TimerItem, TimersPayload } from "@/types/app"

type TimerForm = {
  name: string
  enabled: boolean
  offlineEnabled: boolean
  onlineEnabled: boolean
  offlineInterval: string
  onlineInterval: string
  minimumLines: string
  commandSearch: string
  commands: string[]
  messages: string[]
}

const defaultTimerForm: TimerForm = {
  name: "",
  enabled: true,
  offlineEnabled: true,
  onlineEnabled: true,
  offlineInterval: "60",
  onlineInterval: "10",
  minimumLines: "10",
  commandSearch: "",
  commands: [],
  messages: [""],
}

export function TimerPage() {
  const { data, isLoading, error, refetch, setData } = useJsonQuery<TimersPayload>("/api/app/timers")
  const [isCreateOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState<TimerForm>(defaultTimerForm)
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  const [editingTimer, setEditingTimer] = useState<TimerItem | null>(null)

  useEffect(() => {
    if (data) document.title = `${data.user.login} — таймеры`
  }, [data])

  function updateForm(next: Partial<TimerForm>) {
    setForm((current) => ({ ...current, ...next }))
  }

  function openCreateDialog() {
    setEditingTimer(null)
    setForm(defaultTimerForm)
    setCreateOpen(true)
  }

  function openEditDialog(timer: TimerItem) {
    setEditingTimer(timer)
    setForm({
      name: timer.name,
      enabled: timer.enabled,
      offlineEnabled: timer.offline_enabled,
      onlineEnabled: timer.online_enabled,
      offlineInterval: String(timer.offline_interval_minutes),
      onlineInterval: String(timer.online_interval_minutes),
      minimumLines: String(timer.minimum_lines),
      commandSearch: "",
      commands: timer.commands,
      messages: timer.messages.length ? timer.messages : [""],
    })
    setCreateOpen(true)
  }

  function closeDialog() {
    setCreateOpen(false)
    setEditingTimer(null)
  }

  function addCommand() {
    const raw = form.commandSearch.trim().toLowerCase()
    if (!raw) return
    const command = raw.startsWith("!") ? raw : `!${raw}`
    if (form.commands.includes(command)) return
    updateForm({ commandSearch: "", commands: [...form.commands, command] })
  }

  function updateMessage(index: number, value: string) {
    updateForm({ messages: form.messages.map((message, currentIndex) => (currentIndex === index ? value : message)) })
  }

  function addMessage() {
    if (form.messages.length >= 5) return
    updateForm({ messages: [...form.messages, ""] })
  }

  function removeMessage(index: number) {
    const nextMessages = form.messages.filter((_, currentIndex) => currentIndex !== index)
    updateForm({ messages: nextMessages.length ? nextMessages : [""] })
  }

  async function submitTimer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setActionBusy("save-timer")
    try {
      const result = await requestJson<MutationResult>(editingTimer ? "/api/app/timers/update" : "/api/app/timers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          timer_id: editingTimer?.id,
          name: form.name,
          enabled: form.enabled,
          offline_enabled: form.offlineEnabled,
          online_enabled: form.onlineEnabled,
          offline_interval_minutes: Number.parseInt(form.offlineInterval, 10),
          online_interval_minutes: Number.parseInt(form.onlineInterval, 10),
          minimum_lines: Number.parseInt(form.minimumLines, 10),
          commands: form.commands,
          messages: form.messages.map((message) => message.trim()).filter(Boolean),
        }),
      })
      if (data && result.timers) setData({ ...data, timers: result.timers })
      else await refetch()
      setForm(defaultTimerForm)
      setCreateOpen(false)
      setEditingTimer(null)
      showNotice(
        "success",
        editingTimer ? "Таймер обновлён" : "Таймер добавлен",
        editingTimer ? form.name : "Он начнёт работать по заданным условиям."
      )
    } catch (error) {
      showNotice("error", "Таймер не сохранён", (error as Error).message)
    } finally {
      setActionBusy(null)
    }
  }

  async function toggleTimer(timer: TimerItem, enabled: boolean) {
    setActionBusy(`toggle-${timer.id}`)
    try {
      const result = await requestJson<MutationResult>("/api/app/timers/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ timer_id: timer.id, enabled }),
      })
      if (data && result.timers) setData({ ...data, timers: result.timers })
      else await refetch()
      showNotice("success", enabled ? "Таймер включён" : "Таймер отключён", timer.name)
    } catch (error) {
      showNotice("error", "Таймер не обновлён", (error as Error).message)
    } finally {
      setActionBusy(null)
    }
  }

  async function deleteTimer(timer: TimerItem) {
    if (!window.confirm(`Удалить таймер «${timer.name}»?`)) return
    setActionBusy(`delete-${timer.id}`)
    try {
      const result = await requestJson<MutationResult>("/api/app/timers/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ timer_id: timer.id }),
      })
      if (data && result.timers) setData({ ...data, timers: result.timers })
      else await refetch()
      showNotice("success", "Таймер удалён", timer.name)
    } catch (error) {
      showNotice("error", "Таймер не удалён", (error as Error).message)
    } finally {
      setActionBusy(null)
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-16 w-72" />
        <Skeleton className="h-72 w-full" />
      </div>
    )
  }

  if (error || !data) {
    return <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm">{error ?? "Не удалось загрузить таймеры."}</div>
  }

  return (
    <PageShell>
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <PageHeader title="Таймеры" description="Автоматические сообщения для чата." />
        <Button type="button" onClick={openCreateDialog}>
          <Plus className="size-4" />
          Добавить таймер
        </Button>
      </div>
      {data.timers.length ? (
        <div className="w-full divide-y border-y">
          {data.timers.map((timer) => (
            <TimerRow key={timer.id} actionBusy={actionBusy} timer={timer} onDelete={() => void deleteTimer(timer)} onEdit={() => openEditDialog(timer)} onToggle={(enabled) => void toggleTimer(timer, enabled)} />
          ))}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed bg-muted/30 p-8 text-center">
          <div className="mx-auto flex size-12 items-center justify-center rounded-xl bg-background">
            <Clock3 className="size-5 text-muted-foreground" />
          </div>
          <div className="mt-3 font-medium">Таймеров нет</div>
          <div className="mt-1 text-sm text-muted-foreground">Добавь первый таймер, когда захочешь отправлять сообщения в чат по расписанию.</div>
        </div>
      )}

      <CreateTimerDialog
        actionBusy={actionBusy}
        commandOptions={data.commands}
        isEditing={Boolean(editingTimer)}
        form={form}
        isOpen={isCreateOpen}
        onAddCommand={addCommand}
        onAddMessage={addMessage}
        onClose={closeDialog}
        onRemoveCommand={(command) => updateForm({ commands: form.commands.filter((item) => item !== command) })}
        onRemoveMessage={removeMessage}
        onSubmit={submitTimer}
        onUpdateMessage={updateMessage}
        updateForm={updateForm}
      />
    </PageShell>
  )
}

function TimerRow({
  actionBusy,
  onDelete,
  onEdit,
  onToggle,
  timer,
}: {
  actionBusy: string | null
  onDelete: () => void
  onEdit: () => void
  onToggle: (enabled: boolean) => void
  timer: TimerItem
}) {
  return (
    <div className="grid gap-4 py-4 text-sm lg:grid-cols-[minmax(0,1fr)_170px] lg:items-center lg:gap-6">
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="font-medium">{timer.name}</div>
          <Badge variant={timer.enabled ? "success" : "outline"}>{timer.enabled ? "Включён" : "Отключён"}</Badge>
        </div>
        <div className="text-sm text-muted-foreground">
          Онлайн: {timer.online_enabled ? `${timer.online_interval_minutes} мин` : "выключен"} · Офлайн: {timer.offline_enabled ? `${timer.offline_interval_minutes} мин` : "выключен"} · Минимум строк: {timer.minimum_lines}
        </div>
        <div className="text-sm text-muted-foreground">
          Команды: {timer.commands.length ? timer.commands.join(", ") : "нет"} · Сообщения: {timer.messages.length} · Строк с последней отправки: {timer.line_count}
        </div>
      </div>
      <div className="flex shrink-0 items-center justify-end gap-3 lg:justify-self-end">
        <Switch checked={timer.enabled} disabled={actionBusy === `toggle-${timer.id}`} onCheckedChange={onToggle} />
        <Button type="button" variant="outline" size="icon" aria-label="Редактировать" title="Редактировать" onClick={onEdit}>
          <Pencil className="size-4" />
        </Button>
        <Button type="button" variant="outline" size="icon" aria-label="Удалить" title="Удалить" disabled={actionBusy === `delete-${timer.id}`} onClick={onDelete}>
          <Trash2 className="size-4" />
        </Button>
      </div>
    </div>
  )
}

function CreateTimerDialog({
  actionBusy,
  commandOptions,
  form,
  isEditing,
  isOpen,
  onAddCommand,
  onAddMessage,
  onClose,
  onRemoveCommand,
  onRemoveMessage,
  onSubmit,
  onUpdateMessage,
  updateForm,
}: {
  actionBusy: string | null
  commandOptions: TimersPayload["commands"]
  form: TimerForm
  isEditing: boolean
  isOpen: boolean
  onAddCommand: () => void
  onAddMessage: () => void
  onClose: () => void
  onRemoveCommand: (command: string) => void
  onRemoveMessage: (index: number) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  onUpdateMessage: (index: number, value: string) => void
  updateForm: (next: Partial<TimerForm>) => void
}) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-background/80 p-4 backdrop-blur-sm" role="presentation" onMouseDown={onClose}>
      <div
        aria-modal="true"
        className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-xl border bg-card text-card-foreground shadow-xl"
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-4 border-b p-5">
          <h2 className="text-lg font-semibold">{isEditing ? "Редактировать таймер" : "Создать таймер"}</h2>
          <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label="Закрыть попап">
            <X className="size-4" />
          </Button>
        </div>

        <form className="space-y-7 p-5" onSubmit={onSubmit}>
          <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
            <div className="space-y-2">
              <Label htmlFor="timer-name">Название *</Label>
              <Input id="timer-name" required value={form.name} onChange={(event) => updateForm({ name: event.target.value })} />
            </div>
            <TimerCheckbox checked={form.enabled} label="Включён" onChange={(enabled) => updateForm({ enabled })} />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <TimerCheckbox checked={form.offlineEnabled} label="Работает, когда стрим офлайн" onChange={(offlineEnabled) => updateForm({ offlineEnabled })} />
            <TimerCheckbox checked={form.onlineEnabled} label="Работает, когда стрим онлайн" onChange={(onlineEnabled) => updateForm({ onlineEnabled })} />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <TimerNumberField
              description="Частота отправки, когда стрим офлайн"
              id="timer-offline-interval"
              label="Интервал офлайн *"
              unit="минут"
              value={form.offlineInterval}
              onChange={(offlineInterval) => updateForm({ offlineInterval })}
            />
            <TimerNumberField
              description="Частота отправки, когда стрим онлайн"
              id="timer-online-interval"
              label="Интервал онлайн *"
              unit="минут"
              value={form.onlineInterval}
              onChange={(onlineInterval) => updateForm({ onlineInterval })}
            />
          </div>

          <TimerNumberField
            description="Количество сообщений в чате, после которого можно отправить следующий таймер"
            id="timer-minimum-lines"
            label="Минимум строк *"
            unit="строк"
            value={form.minimumLines}
            onChange={(minimumLines) => updateForm({ minimumLines })}
          />

          <TimerSection title="Команды">
            <div className="flex gap-3 rounded-xl bg-secondary/60 p-4 text-sm text-muted-foreground">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-primary" />
              <div>Бот может по очереди запускать твои кастомные команды с интервалом таймера, чтобы не писать уникальные сообщения каждый раз.</div>
            </div>
            <div className="space-y-2">
              <Label htmlFor="timer-command">Добавить команду</Label>
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Input id="timer-command" className="pl-9" list="timer-command-options" placeholder="Поиск команд..." value={form.commandSearch} onChange={(event) => updateForm({ commandSearch: event.target.value })} />
                  <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                </div>
                <Button type="button" variant="outline" onClick={onAddCommand}>
                  Добавить
                </Button>
              </div>
              <datalist id="timer-command-options">
                {commandOptions.map((command) => (
                  <option key={command.name} value={command.name}>
                    {command.response_text}
                  </option>
                ))}
              </datalist>
              {form.commands.length ? (
                <div className="flex flex-wrap gap-2">
                  {form.commands.map((command) => (
                    <button key={command} type="button" className="rounded-lg border px-3 py-1 text-sm" onClick={() => onRemoveCommand(command)}>
                      {command} x
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          </TimerSection>

          <TimerSection title="Сообщения">
            <div className="flex gap-3 rounded-xl bg-secondary/60 p-4 text-sm text-muted-foreground">
              <MessageSquareText className="mt-0.5 size-4 shrink-0 text-primary" />
              <div>Бот может отправлять до 5 кастомных сообщений, если для таймера не подходит команда.</div>
            </div>
            <div className="space-y-3">
              {form.messages.map((message, index) => (
                <div className="flex items-center gap-3" key={index}>
                  <Input placeholder={`Сообщение #${index + 1}`} value={message} onChange={(event) => onUpdateMessage(index, event.target.value)} />
                  <Button type="button" variant="ghost" size="icon" aria-label="Удалить сообщение" onClick={() => onRemoveMessage(index)}>
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              ))}
              <Button type="button" variant="outline" onClick={onAddMessage} disabled={form.messages.length >= 5}>
                <Plus className="size-4" />
                Добавить сообщение
              </Button>
            </div>
          </TimerSection>

          <div className="flex flex-col-reverse gap-2 border-t pt-5 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" onClick={onClose}>
              Отмена
            </Button>
            <Button type="submit" disabled={actionBusy === "save-timer"}>
              {actionBusy === "save-timer" ? "Сохраняю..." : "Сохранить"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

function TimerCheckbox({ checked, label, onChange }: { checked: boolean; label: string; onChange: (checked: boolean) => void }) {
  return (
    <label className="inline-flex items-center gap-3 text-sm font-medium">
      <input className="size-4 accent-primary" type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      {label}
    </label>
  )
}

function TimerNumberField({
  description,
  id,
  label,
  onChange,
  unit,
  value,
}: {
  description: string
  id: string
  label: string
  onChange: (value: string) => void
  unit: string
  value: string
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <div className="relative">
        <Input id={id} inputMode="numeric" type="number" min="0" required value={value} onChange={(event) => onChange(event.target.value)} />
        <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-muted-foreground">{unit}</span>
      </div>
      <div className="text-xs text-muted-foreground">{description}</div>
    </div>
  )
}

function TimerSection({ children, title }: { children: ReactNode; title: string }) {
  return (
    <section className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="text-sm font-semibold uppercase text-muted-foreground">{title}</div>
        <div className="h-px flex-1 bg-border" />
      </div>
      {children}
    </section>
  )
}
