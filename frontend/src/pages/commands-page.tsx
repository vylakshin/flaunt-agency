import { ChevronDown, CircleAlert, Loader2, Pencil, Plus, Trash2, X } from "lucide-react"
import { useEffect, useMemo, useState, type Dispatch, type FormEvent, type SetStateAction } from "react"

import { PageHeader } from "@/components/app/page-header"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { Toast, type ToastNotice } from "@/components/ui/toast"
import { useJsonQuery } from "@/hooks/use-json-query"
import { requestJson } from "@/lib/api"
import type { CommandItem, CommandsMutationResult, CommandsPayload } from "@/types/app"

type CommandForm = {
  name: string
  enabled: boolean
  response_text: string
  cooldown_seconds: string
  allowed_roles: string[]
  aliases: string[]
  keywords: string[]
}

type CommandTab = "standard" | "custom"
type CommandDialogTab = "general" | "aliases" | "conditions"

const commandRoles = [
  { value: "streamer", label: "Стример" },
  { value: "moderator", label: "Модер" },
  { value: "editor", label: "Редактор" },
  { value: "subscriber", label: "Подписчик" },
  { value: "non_subscriber", label: "Не подписчик" },
  { value: "vip", label: "VIP" },
]

export function CommandsPage() {
  const { data, isLoading, error, refetch, setData } = useJsonQuery<CommandsPayload>("/api/app/commands")
  const [notice, setNotice] = useState<ToastNotice | null>(null)
  const [busyCommand, setBusyCommand] = useState<string | null>(null)
  const [isCreateOpen, setCreateOpen] = useState(false)
  const [editingCommand, setEditingCommand] = useState<CommandItem | null>(null)
  const [isCommandListOpen, setCommandListOpen] = useState(true)
  const [activeTab, setActiveTab] = useState<CommandTab>("standard")
  const [form, setForm] = useState<CommandForm>({
    name: "!",
    enabled: true,
    response_text: "",
    cooldown_seconds: "5",
    allowed_roles: [],
    aliases: [],
    keywords: [],
  })

  useEffect(() => {
    if (data) document.title = `${data.user.login} — команды`
  }, [data])

  function resetForm() {
    setForm({ name: "!", enabled: true, response_text: "", cooldown_seconds: "5", allowed_roles: [], aliases: [], keywords: [] })
  }

  function openCreateDialog() {
    setEditingCommand(null)
    resetForm()
    setCreateOpen(true)
  }

  function openEditDialog(command: CommandItem) {
    if (command.is_builtin) return
    setEditingCommand(command)
    setForm({
      name: command.name,
      enabled: command.enabled,
      response_text: command.response_text,
      cooldown_seconds: String(command.cooldown_seconds),
      allowed_roles: command.allowed_roles,
      aliases: command.aliases,
      keywords: command.keywords,
    })
    setCreateOpen(true)
  }

  function updateName(value: string) {
    const normalized = value.startsWith("!") ? value : `!${value.replace(/^!+/, "")}`
    setForm((current) => ({ ...current, name: normalized }))
  }

  async function updateCommandList(result: CommandsMutationResult) {
    if (data && result.commands) {
      setData({ ...data, commands: result.commands })
      return
    }
    await refetch()
  }

  async function toggleCommand(command: CommandItem, enabled: boolean) {
    setBusyCommand(`toggle-${command.name}`)
    setNotice(null)
    try {
      const result = await requestJson<CommandsMutationResult>("/api/app/commands/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: command.name, enabled }),
      })
      await updateCommandList(result)
    } catch (error) {
      setNotice({ type: "error", title: "Команда не обновлена", text: (error as Error).message })
    } finally {
      setBusyCommand(null)
    }
  }

  async function toggleCommandGroup(enabled: boolean) {
    setBusyCommand("toggle-group")
    setNotice(null)
    try {
      const result = await requestJson<CommandsMutationResult>("/api/app/commands/toggle-all", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled, group: "builtin" }),
      })
      await updateCommandList(result)
      setNotice({
        type: "success",
        title: enabled ? "Команды викторины включены" : "Команды викторины отключены",
        text: enabled ? "Команды викторины снова отвечают в чате." : "Команды викторины отключены группой.",
      })
    } catch (error) {
      setNotice({ type: "error", title: "Команды не обновлены", text: (error as Error).message })
    } finally {
      setBusyCommand(null)
    }
  }

  async function deleteCommand(command: CommandItem) {
    if (!window.confirm(`Удалить команду ${command.name}?`)) return
    setBusyCommand(`delete-${command.name}`)
    setNotice(null)
    try {
      const result = await requestJson<CommandsMutationResult>("/api/app/commands/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: command.name }),
      })
      await updateCommandList(result)
      setNotice({ type: "warning", title: "Команда удалена", text: `${command.name} больше не отвечает в чате.` })
    } catch (error) {
      setNotice({ type: "error", title: "Команда не удалена", text: (error as Error).message })
    } finally {
      setBusyCommand(null)
    }
  }

  async function createCommand(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusyCommand("create")
    setNotice(null)
    try {
      const result = await requestJson<CommandsMutationResult>(editingCommand ? "/api/app/commands/update" : "/api/app/commands", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name,
          enabled: form.enabled,
          response_text: form.response_text,
          cooldown_seconds: Number.parseFloat(form.cooldown_seconds),
          allowed_roles: form.allowed_roles,
          aliases: form.aliases,
          keywords: form.keywords,
        }),
      })
      await updateCommandList(result)
      setCreateOpen(false)
      setEditingCommand(null)
      resetForm()
      setNotice(editingCommand ? { type: "success", title: "Команда обновлена", text: `${form.name} сохранена.` } : { type: "success", title: "Команда добавлена", text: `${form.name} готова отвечать в чате.` })
    } catch (error) {
      setNotice({ type: "error", title: "Команда не создана", text: (error as Error).message })
    } finally {
      setBusyCommand(null)
    }
  }

  const commands = useMemo(() => data?.commands ?? [], [data?.commands])
  const quizCommands = useMemo(() => commands.filter((command) => command.is_builtin), [commands])
  const customCommands = useMemo(() => commands.filter((command) => !command.is_builtin), [commands])
  const enabledQuizCommandsCount = useMemo(() => quizCommands.filter((command) => command.enabled).length, [quizCommands])
  const enabledCustomCommandsCount = useMemo(() => customCommands.filter((command) => command.enabled).length, [customCommands])
  const allQuizCommandsEnabled = quizCommands.length > 0 && enabledQuizCommandsCount === quizCommands.length

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-16 w-72" />
        <Skeleton className="h-96 w-full" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <Alert variant="destructive">
        <CircleAlert className="mb-3 size-5" />
        <AlertTitle>Команды не загрузились</AlertTitle>
        <AlertDescription>{error ?? "Сервер вернул пустой ответ."}</AlertDescription>
      </Alert>
    )
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Команды" description="Стандартные команды сгруппированы по разделам, кастомные команды добавляются отдельно." />

      <Toast notice={notice} onClose={() => setNotice(null)} />

      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="inline-grid rounded-lg border bg-muted/30 p-1 sm:grid-cols-2">
          <button
            type="button"
            className={activeTab === "standard" ? "rounded-md bg-background px-4 py-2 text-sm font-medium shadow-sm" : "rounded-md px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground"}
            onClick={() => setActiveTab("standard")}
          >
            Стандартные команды
            <span className="ml-2 text-xs text-muted-foreground">{quizCommands.length}</span>
          </button>
          <button
            type="button"
            className={activeTab === "custom" ? "rounded-md bg-background px-4 py-2 text-sm font-medium shadow-sm" : "rounded-md px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground"}
            onClick={() => setActiveTab("custom")}
          >
            Кастомные команды
            <span className="ml-2 text-xs text-muted-foreground">{customCommands.length}</span>
          </button>
        </div>
        {activeTab === "custom" ? (
          <Button type="button" onClick={openCreateDialog}>
            <Plus className="size-4" />
            Добавить команду
          </Button>
        ) : null}
      </div>

      <div className="text-sm text-muted-foreground">
        Викторина: {enabledQuizCommandsCount} из {quizCommands.length}. Кастомные: {enabledCustomCommandsCount} из {customCommands.length}.
      </div>

      {activeTab === "standard" ? (
        <div className="w-full border-y">
          <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
            <button
              type="button"
              className="flex min-w-0 items-center gap-3 text-left"
              onClick={() => setCommandListOpen((current) => !current)}
              aria-expanded={isCommandListOpen}
            >
              <ChevronDown className={isCommandListOpen ? "size-4 shrink-0 transition-transform" : "-rotate-90 size-4 shrink-0 transition-transform"} />
              <span className="min-w-0">
                <span className="block font-semibold">Команды викторины</span>
                <span className="block text-sm text-muted-foreground">Системные команды игры. Пользователи не могут добавлять сюда новые команды.</span>
              </span>
            </button>
            <div className="flex items-center gap-3 sm:justify-end">
              {busyCommand === "toggle-group" ? <Loader2 className="size-4 animate-spin text-muted-foreground" /> : null}
              <span className="text-sm text-muted-foreground">{allQuizCommandsEnabled ? "Группа включена" : enabledQuizCommandsCount === 0 ? "Группа отключена" : "Частично включена"}</span>
              <Switch
                checked={allQuizCommandsEnabled}
                onCheckedChange={(enabled) => void toggleCommandGroup(enabled)}
                disabled={quizCommands.length === 0 || busyCommand !== null}
              />
            </div>
          </div>

          {isCommandListOpen && quizCommands.length ? (
            <div className="divide-y">
              {quizCommands.map((command) => (
                <CommandRow
                  key={command.name}
                  busyCommand={busyCommand}
                  command={command}
                  onDelete={deleteCommand}
                  onEdit={openEditDialog}
                  onToggle={toggleCommand}
                />
              ))}
            </div>
          ) : null}

          {isCommandListOpen && !quizCommands.length ? (
            <div className="border-t border-dashed bg-muted/30 p-8 text-center">
              <div className="font-medium">Команд викторины пока нет</div>
              <div className="mt-1 text-sm text-muted-foreground">Эта группа заполняется системными командами игры.</div>
            </div>
          ) : null}
        </div>
      ) : null}

      {activeTab === "custom" ? (
        <div className="w-full divide-y border-y">
          <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="font-semibold">Кастомные команды</div>
              <div className="text-sm text-muted-foreground">Все пользовательские команды этого канала.</div>
            </div>
            <Badge variant="outline">{customCommands.length}</Badge>
          </div>
          {customCommands.length ? (
            customCommands.map((command) => (
              <CommandRow
                key={command.name}
                busyCommand={busyCommand}
                command={command}
                onDelete={deleteCommand}
                onEdit={openEditDialog}
                onToggle={toggleCommand}
              />
            ))
          ) : (
            <div className="border-t border-dashed bg-muted/30 p-8 text-center">
              <div className="font-medium">Кастомных команд пока нет</div>
              <div className="mt-1 text-sm text-muted-foreground">Нажми “Добавить команду”, чтобы создать свою команду для чата.</div>
            </div>
          )}
        </div>
      ) : null}

      <CommandDialog
        key={isCreateOpen ? editingCommand?.name ?? "create" : "closed"}
        form={form}
        isEditing={Boolean(editingCommand)}
        isBusy={busyCommand === "create"}
        isOpen={isCreateOpen}
        onClose={() => {
          setCreateOpen(false)
          setEditingCommand(null)
        }}
        onSubmit={createCommand}
        setForm={setForm}
        updateName={updateName}
      />
    </div>
  )
}

function CommandRow({
  busyCommand,
  command,
  onDelete,
  onEdit,
  onToggle,
}: {
  busyCommand: string | null
  command: CommandItem
  onDelete: (command: CommandItem) => void
  onEdit: (command: CommandItem) => void
  onToggle: (command: CommandItem, enabled: boolean) => void
}) {
  const isBusy = busyCommand === "toggle-group" || busyCommand === `toggle-${command.name}` || busyCommand === `delete-${command.name}`

  return (
    <div className="grid min-h-14 gap-4 py-4 text-sm lg:grid-cols-[220px_minmax(0,1fr)_170px] lg:items-center lg:gap-6">
      <code className="min-w-0 break-all pr-2 font-semibold text-foreground">{command.name}</code>

      <div className="min-w-0">
        <div className="truncate font-medium text-foreground">
          {command.is_builtin ? command.description : command.response_text}
        </div>
        {!command.is_builtin ? (
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span>КД: {command.cooldown_seconds} сек</span>
            {command.aliases.length ? <span>Вариации: {command.aliases.join(", ")}</span> : null}
            {command.keywords.length ? <span>Кейворды: {command.keywords.join(", ")}</span> : null}
            {command.allowed_roles.length ? (
              command.allowed_roles.map((role) => (
                <Badge key={role} variant="outline">
                  {commandRoles.find((item) => item.value === role)?.label ?? role}
                </Badge>
              ))
            ) : (
              <Badge variant="outline">Все пользователи</Badge>
            )}
          </div>
        ) : null}
      </div>

      <div className="flex items-center gap-3 lg:justify-end">
        {isBusy ? <Loader2 className="size-4 animate-spin text-muted-foreground" /> : null}
        <Switch checked={command.enabled} onCheckedChange={(enabled) => onToggle(command, enabled)} disabled={isBusy} />
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="uppercase text-primary"
          aria-label="Редактировать"
          title="Редактировать"
          disabled={command.is_builtin || isBusy}
          onClick={() => onEdit(command)}
        >
          <Pencil className="size-4" />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="uppercase text-primary"
          aria-label="Удалить"
          title="Удалить"
          disabled={!command.can_delete || isBusy}
          onClick={() => onDelete(command)}
        >
          <Trash2 className="size-4" />
        </Button>
      </div>
    </div>
  )
}

function CreateCommandDialog({
  form,
  isBusy,
  isEditing,
  isOpen,
  onClose,
  onSubmit,
  setForm,
  updateName,
}: {
  form: CommandForm
  isBusy: boolean
  isEditing: boolean
  isOpen: boolean
  onClose: () => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  setForm: Dispatch<SetStateAction<CommandForm>>
  updateName: (value: string) => void
}) {
  if (!isOpen) return null

  function toggleRole(role: string) {
    setForm((current) => ({
      ...current,
      allowed_roles: current.allowed_roles.includes(role)
        ? current.allowed_roles.filter((item) => item !== role)
        : [...current.allowed_roles, role],
    }))
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-background/80 p-4 backdrop-blur-sm" role="presentation" onMouseDown={onClose}>
      <div
        aria-modal="true"
        className="grid max-h-[90vh] w-full max-w-4xl overflow-hidden rounded-lg border bg-card text-card-foreground shadow-xl md:grid-cols-[280px_minmax(0,1fr)]"
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="border-b p-4 md:col-span-2">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-lg font-semibold">{isEditing ? "Редактировать команду" : "Создать команду"}</h2>
            <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label="Закрыть попап">
              <X className="size-4" />
            </Button>
          </div>
        </div>

        <div className="hidden border-r bg-muted/30 p-4 md:block">
          <div className="rounded-md bg-secondary px-3 py-2 text-sm font-medium text-secondary-foreground">Основные</div>
          <div className="px-3 py-2 text-sm font-medium text-muted-foreground">Вариации и кейворды</div>
          <div className="px-3 py-2 text-sm font-medium text-muted-foreground">Условия</div>
        </div>

        <form className="flex min-h-0 flex-col" onSubmit={onSubmit}>
          <div className="grid flex-1 gap-5 overflow-y-auto p-4 md:p-6">
            <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-center">
              <label className="space-y-2">
                <span className="text-sm font-medium text-primary">Команда</span>
                <Input autoFocus value={form.name} disabled={isEditing} onChange={(event) => updateName(event.target.value)} />
              </label>
              <label className="flex items-center gap-3 pt-2 sm:pt-7">
                <Switch checked={form.enabled} onCheckedChange={(enabled) => setForm((current) => ({ ...current, enabled }))} />
                <span className="font-medium">Включена</span>
              </label>
            </div>

            <label className="space-y-2">
              <span className="text-sm font-medium text-muted-foreground">Ответ ({form.response_text.length}/500)</span>
              <textarea
                className="min-h-32 w-full rounded-md border bg-background px-3 py-3 text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring"
                maxLength={500}
                value={form.response_text}
                onChange={(event) => setForm((current) => ({ ...current, response_text: event.target.value }))}
              />
            </label>

            <label className="space-y-2">
              <span className="text-sm font-medium text-muted-foreground">КД</span>
              <div className="relative">
                <Input
                  inputMode="decimal"
                  min="0"
                  step="1"
                  type="number"
                  value={form.cooldown_seconds}
                  onChange={(event) => setForm((current) => ({ ...current, cooldown_seconds: event.target.value }))}
                />
                <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-muted-foreground">сек</span>
              </div>
            </label>

            <div className="space-y-3">
              <div>
                <div className="text-sm font-medium text-muted-foreground">Кто может использовать</div>
                <div className="mt-1 text-xs text-muted-foreground">Если ничего не выбрано, команду могут использовать все пользователи.</div>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {commandRoles.map((role) => (
                  <label key={role.value} className="flex items-center justify-between gap-3 rounded-md border bg-background px-3 py-2">
                    <span className="text-sm font-medium">{role.label}</span>
                    <Switch checked={form.allowed_roles.includes(role.value)} onCheckedChange={() => toggleRole(role.value)} />
                  </label>
                ))}
              </div>
            </div>
          </div>

          <div className="flex justify-end border-t p-4">
            <Button type="submit" disabled={isBusy}>
              {isBusy ? <Loader2 className="size-4 animate-spin" /> : null}
              Сохранить
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}

function CommandDialog({
  form,
  isBusy,
  isEditing,
  isOpen,
  onClose,
  onSubmit,
  setForm,
  updateName,
}: {
  form: CommandForm
  isBusy: boolean
  isEditing: boolean
  isOpen: boolean
  onClose: () => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  setForm: Dispatch<SetStateAction<CommandForm>>
  updateName: (value: string) => void
}) {
  const [dialogTab, setDialogTab] = useState<CommandDialogTab>("general")
  const [aliasInput, setAliasInput] = useState("!")
  const [keywordInput, setKeywordInput] = useState("")

  if (!isOpen) return null

  const dialogTabs: Array<{ id: CommandDialogTab; label: string }> = [
    { id: "general", label: "Основные" },
    { id: "aliases", label: "Вариации и кейворды" },
    { id: "conditions", label: "Условия" },
  ]

  function toggleRole(role: string) {
    setForm((current) => ({
      ...current,
      allowed_roles: current.allowed_roles.includes(role)
        ? current.allowed_roles.filter((item) => item !== role)
        : [...current.allowed_roles, role],
    }))
  }

  function addAlias() {
    const raw = aliasInput.trim()
    const normalized = raw.startsWith("!") ? raw.split(/\s+/)[0].toLowerCase() : `!${raw.replace(/^!+/, "").split(/\s+/)[0].toLowerCase()}`
    if (normalized.length < 2 || normalized === form.name || form.aliases.includes(normalized)) return
    setForm((current) => ({ ...current, aliases: [...current.aliases, normalized] }))
    setAliasInput("!")
  }

  function addKeyword() {
    const normalized = keywordInput.trim().toLowerCase().replace(/^!+/, "")
    if (!normalized || form.keywords.includes(normalized)) return
    setForm((current) => ({ ...current, keywords: [...current.keywords, normalized] }))
    setKeywordInput("")
  }

  function removeAlias(alias: string) {
    setForm((current) => ({ ...current, aliases: current.aliases.filter((item) => item !== alias) }))
  }

  function removeKeyword(keyword: string) {
    setForm((current) => ({ ...current, keywords: current.keywords.filter((item) => item !== keyword) }))
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-background/80 p-4 backdrop-blur-sm" role="presentation" onMouseDown={onClose}>
      <div
        aria-modal="true"
        className="grid max-h-[90vh] w-full max-w-4xl overflow-hidden rounded-lg border bg-card text-card-foreground shadow-xl md:grid-cols-[280px_minmax(0,1fr)]"
        role="dialog"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="border-b p-4 md:col-span-2">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-lg font-semibold">{isEditing ? "Редактировать команду" : "Создать команду"}</h2>
            <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label="Закрыть попап">
              <X className="size-4" />
            </Button>
          </div>
        </div>

        <div className="grid content-start gap-1 border-b bg-muted/30 p-2 md:border-b-0 md:border-r md:p-3">
          {dialogTabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={
                dialogTab === tab.id
                  ? "rounded-md bg-secondary px-3 py-2 text-left text-sm font-medium text-secondary-foreground"
                  : "rounded-md px-3 py-2 text-left text-sm font-medium text-muted-foreground hover:bg-muted hover:text-foreground"
              }
              onClick={() => setDialogTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <form className="flex min-h-0 flex-col" onSubmit={onSubmit}>
          <div className="grid flex-1 gap-5 overflow-y-auto p-4 md:p-6">
            {dialogTab === "general" ? (
              <>
                <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-center">
                  <label className="space-y-2">
                    <span className="text-sm font-medium text-primary">Команда</span>
                    <Input autoFocus value={form.name} disabled={isEditing} onChange={(event) => updateName(event.target.value)} />
                  </label>
                  <label className="flex items-center gap-3 pt-2 sm:pt-7">
                    <Switch checked={form.enabled} onCheckedChange={(enabled) => setForm((current) => ({ ...current, enabled }))} />
                    <span className="font-medium">Включена</span>
                  </label>
                </div>

                <label className="space-y-2">
                  <span className="text-sm font-medium text-muted-foreground">Ответ ({form.response_text.length}/500)</span>
                  <textarea
                    className="min-h-32 w-full rounded-md border bg-background px-3 py-3 text-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring"
                    maxLength={500}
                    value={form.response_text}
                    onChange={(event) => setForm((current) => ({ ...current, response_text: event.target.value }))}
                  />
                </label>

                <label className="space-y-2">
                  <span className="text-sm font-medium text-muted-foreground">КД</span>
                  <div className="relative">
                    <Input
                      inputMode="decimal"
                      min="0"
                      step="1"
                      type="number"
                      value={form.cooldown_seconds}
                      onChange={(event) => setForm((current) => ({ ...current, cooldown_seconds: event.target.value }))}
                    />
                    <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-muted-foreground">сек</span>
                  </div>
                </label>
              </>
            ) : null}

            {dialogTab === "aliases" ? (
              <div className="space-y-8">
                <section className="space-y-3">
                  <div className="flex items-center gap-3">
                    <div className="text-sm font-semibold uppercase text-muted-foreground">Вариации</div>
                    <div className="h-px flex-1 bg-border" />
                  </div>
                  <label className="space-y-2">
                    <span className="text-xs font-medium text-muted-foreground">Добавить вариацию</span>
                    <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
                      <Input
                        value={aliasInput}
                        onChange={(event) => setAliasInput(event.target.value.startsWith("!") ? event.target.value : `!${event.target.value}`)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault()
                            addAlias()
                          }
                        }}
                        placeholder="!twitter"
                      />
                      <Button type="button" variant="outline" className="uppercase text-primary" onClick={addAlias}>
                        Добавить
                      </Button>
                    </div>
                  </label>
                  <p className="text-xs text-muted-foreground">Альтернативные названия для запуска команды. Нажми Enter или “Добавить”.</p>
                  {form.aliases.length ? (
                    <div className="flex flex-wrap gap-2">
                      {form.aliases.map((alias) => (
                        <Badge key={alias} variant="outline" className="gap-2">
                          {alias}
                          <button type="button" onClick={() => removeAlias(alias)} aria-label={`Удалить ${alias}`}>
                            <X className="size-3" />
                          </button>
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                </section>

                <section className="space-y-3">
                  <div className="flex items-center gap-3">
                    <div className="text-sm font-semibold uppercase text-muted-foreground">Кейворды</div>
                    <div className="h-px flex-1 bg-border" />
                  </div>
                  <div className="rounded-md border border-primary/20 bg-primary/10 px-4 py-3 text-sm text-primary">
                    Кейворды срабатывают по тексту сообщения и не требуют восклицательного знака.
                  </div>
                  <label className="space-y-2">
                    <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
                      <Input
                        value={keywordInput}
                        onChange={(event) => setKeywordInput(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault()
                            addKeyword()
                          }
                        }}
                        placeholder="Добавить кейворд"
                      />
                      <Button type="button" variant="outline" className="uppercase text-primary" onClick={addKeyword}>
                        Добавить
                      </Button>
                    </div>
                  </label>
                  <p className="text-xs text-muted-foreground">Кейворд может быть в любом месте сообщения. Нажми Enter или “Добавить”.</p>
                  {form.keywords.length ? (
                    <div className="flex flex-wrap gap-2">
                      {form.keywords.map((keyword) => (
                        <Badge key={keyword} variant="outline" className="gap-2">
                          {keyword}
                          <button type="button" onClick={() => removeKeyword(keyword)} aria-label={`Удалить ${keyword}`}>
                            <X className="size-3" />
                          </button>
                        </Badge>
                      ))}
                    </div>
                  ) : null}
                </section>
              </div>
            ) : null}

            {dialogTab === "conditions" ? (
              <div className="space-y-3">
                <div>
                  <div className="text-sm font-medium text-muted-foreground">Кто может использовать</div>
                  <div className="mt-1 text-xs text-muted-foreground">Если ничего не выбрано, команду могут использовать все пользователи.</div>
                </div>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {commandRoles.map((role) => (
                    <label key={role.value} className="flex items-center justify-between gap-3 rounded-md border bg-background px-3 py-2">
                      <span className="text-sm font-medium">{role.label}</span>
                      <Switch checked={form.allowed_roles.includes(role.value)} onCheckedChange={() => toggleRole(role.value)} />
                    </label>
                  ))}
                </div>
              </div>
            ) : null}
          </div>

          <div className="flex justify-end border-t p-4">
            <Button type="submit" disabled={isBusy}>
              {isBusy ? <Loader2 className="size-4 animate-spin" /> : null}
              Сохранить
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
