import { Bot, CircleHelp, LogIn, MessageSquareText, Radio, ShieldCheck, Sparkles, Timer, Trophy } from "lucide-react"
import { useEffect, useMemo } from "react"
import { useSearchParams } from "react-router-dom"

import { BrandLogo } from "@/components/app/brand-logo"
import { ThemeProvider } from "@/components/app/theme-provider"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"

const features = [
  { icon: CircleHelp, title: "Викторина", text: "Вопросы в чате и overlay для OBS" },
  { icon: MessageSquareText, title: "Команды", text: "Кастомные команды и роли" },
  { icon: Timer, title: "Таймеры", text: "Автосообщения по расписанию" },
  { icon: Trophy, title: "Автоставка", text: "Predictions для Dota 2 и CS2" },
  { icon: Bot, title: "Розыгрыши", text: "Giveaway из панели" },
  { icon: ShieldCheck, title: "Twitch OAuth", text: "Безопасный вход" },
]

export function LoginPage() {
  const [params] = useSearchParams()
  const error = params.get("error") || ""
  const warning = params.get("warning") || ""
  const highlights = useMemo(() => features.slice(0, 3), [])

  useEffect(() => {
    document.title = "Flaunt — вход"
  }, [])

  return (
    <ThemeProvider>
      <main className="login-stage">
        <div className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-4 py-8 sm:px-8">
          <header className="flex items-center justify-between">
            <BrandLogo subtitle="Панель стримера" />
          </header>

          <div className="grid flex-1 items-center gap-12 py-12 lg:grid-cols-[1.2fr_380px] lg:gap-16">
            <section className="space-y-8">
              <div className="space-y-4">
                <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">Flaunt</p>
                <h1 className="font-display text-4xl font-bold leading-[1.08] tracking-tight sm:text-5xl">
                  Панель для
                  <br />
                  <span className="brand-text">Twitch-стримера</span>
                </h1>
                <p className="max-w-lg text-base leading-relaxed text-muted-foreground">
                  Викторина, команды, таймеры, розыгрыши и автоставки. Подключи GSI — бот сам откроет и закроет predictions.
                </p>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                {highlights.map((item) => {
                  const Icon = item.icon
                  return (
                    <div key={item.title} className="panel-muted p-4">
                      <Icon className="size-5 text-primary" />
                      <div className="mt-3 font-semibold">{item.title}</div>
                      <p className="mt-1 text-xs text-muted-foreground">{item.text}</p>
                    </div>
                  )
                })}
              </div>
            </section>

            <div className="panel p-6 shadow-[var(--flaunt-shadow-lg)]">
              <div className="brand-mark mb-5 flex size-11 items-center justify-center rounded-xl">
                <Sparkles className="size-5" />
              </div>
              <h2 className="font-display text-xl font-bold">Войти через Twitch</h2>
              <p className="mt-1 text-sm text-muted-foreground">Нужны права владельца или модератора канала.</p>

              <div className="mt-5 space-y-3">
                {error ? (
                  <Alert variant="destructive">
                    <AlertTitle>Ошибка входа</AlertTitle>
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                ) : null}
                {warning ? (
                  <Alert variant="warning">
                    <AlertTitle>Проверь доступ</AlertTitle>
                    <AlertDescription>{warning}</AlertDescription>
                  </Alert>
                ) : null}

                <Button asChild variant="brand" size="lg" className="w-full">
                  <a href="/auth/twitch/login">
                    <LogIn className="size-5" />
                    Продолжить с Twitch
                  </a>
                </Button>
              </div>
            </div>
          </div>

          <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-6 text-xs text-muted-foreground">
            <span>GSI: Win+R → команда из раздела «Автоставка»</span>
            <span className="flex items-center gap-1">
              <Radio className="size-3" />
              Dota 2 · CS2
            </span>
          </footer>
        </div>
      </main>
    </ThemeProvider>
  )
}
