import { PageHeader } from "@/components/app/page-header"
import { PageShell } from "@/components/app/page-shell"
import {
  dashboardSettingsFromPayload,
  GameSettingsCard,
  serializeDashboardSettings,
  syncDashboardSettingsChatMode,
  type DashboardSettingsForm,
  type SettingsSaveState,
} from "@/components/app/game-settings-card"
import { Skeleton } from "@/components/ui/skeleton"
import { showNotice } from "@/lib/notify"
import { useJsonQuery } from "@/hooks/use-json-query"
import { requestJson } from "@/lib/api"
import type { DashboardPayload, MutationResult } from "@/types/app"
import { useEffect, useRef, useState } from "react"

export function SettingsPage() {
  const { data, isLoading, error } = useJsonQuery<DashboardPayload>("/api/app/dashboard")
  const [formState, setFormState] = useState<DashboardSettingsForm | null>(null)
  const [settingsSaveState, setSettingsSaveState] = useState<SettingsSaveState>("idle")
  const lastSavedSettingsRef = useRef("")

  useEffect(() => {
    if (!data) return

    const nextFormState = dashboardSettingsFromPayload(data)
    lastSavedSettingsRef.current = serializeDashboardSettings(nextFormState)
    setFormState(nextFormState)
    setSettingsSaveState("idle")
  }, [data])

  useEffect(() => {
    if (!formState || !data) return

    const serialized = serializeDashboardSettings(formState)
    if (serialized === lastSavedSettingsRef.current) return

    setSettingsSaveState("saving")
    const timeoutId = window.setTimeout(() => {
      void saveSettingsSnapshot(formState)
    }, 650)

    return () => window.clearTimeout(timeoutId)
  }, [data, formState])

  function updateSettings(next: Partial<DashboardSettingsForm>) {
    setFormState((current) => (current ? syncDashboardSettingsChatMode({ ...current, ...next }) : current))
  }

  async function saveSettingsSnapshot(snapshot: DashboardSettingsForm) {
    const serialized = serializeDashboardSettings(snapshot)

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
          quiet_mode: snapshot.quiet_mode,
          chat_questions_enabled: snapshot.chat_questions_enabled,
          chat_outcomes_enabled: snapshot.chat_outcomes_enabled,
        }),
      })
      lastSavedSettingsRef.current = serialized
      setSettingsSaveState("saved")
    } catch (error) {
      setSettingsSaveState("error")
      showNotice("error", "Настройки не сохранены", (error as Error).message)
    }
  }

  if (isLoading) {
    return (
      <PageShell>
        <Skeleton className="h-16 w-72" />
        <Skeleton className="h-96 w-full" />
      </PageShell>
    )
  }

  if (error || !data || !formState) {
    return <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm">{error ?? "Не удалось загрузить настройки."}</div>
  }

  return (
    <PageShell>
      <PageHeader title="Настройки" description={`Канал ${data.user.display_name}. Параметры сохраняются автоматически без перезагрузки.`} />

      <GameSettingsCard data={data} formState={formState} isSaving={settingsSaveState === "saving"} settingsSaveState={settingsSaveState} updateSettings={updateSettings} />
    </PageShell>
  )
}
