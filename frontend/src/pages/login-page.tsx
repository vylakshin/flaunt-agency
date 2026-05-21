import { Bot, CircleHelp, LogIn, MessageSquareText, Radio, ShieldCheck, Sparkles, Timer, Trophy, Zap } from "lucide-react"
import { useEffect, useMemo } from "react"
import { useSearchParams } from "react-router-dom"

import { BrandLogo } from "@/components/app/brand-logo"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

const features = [
  { icon: CircleHelp, title: "Викторина", text: "Вопросы в чате и overlay для OBS" },
  { icon: MessageSquareText, title: "Команды", text: "Кастомные команды и роли доступа" },
  { icon: Timer, title: "Таймеры", text: "Автосообщения по расписанию стрима" },
  { icon: Trophy, title: "Автоставка", text: "Predictions для Dota 2 и CS2" },
  { icon: Bot, title: "Розыгрыши", text: "Giveaway прямо из панели" },
  { icon: ShieldCheck, title: "Безопасность", text: "Вход через Twitch OAuth" },
]

export function LoginPage() {
  const [params] = useSearchParams()
  const error = params.get("error") || ""
  const warning = params.get("warning") || ""

  useEffect(() => {
    document.title = "Flaunt — вход"
  }, [])

  const highlights = useMemo(() => features.slice(0, 3), [])

  return (
    <main className="login-stage">
      <div className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-4 py-8 sm:px-8">
        <header className="flex items-center justify-between gap-4">
          <BrandLogo subtitle="Stream control panel" />
          <Badge variant="brand" className="hidden gap-1.5 sm:inline-flex">
            <Zap className="size-3" />
            Twitch-native
          </Badge>
        </header>

        <div className="grid flex-1 items-center gap-12 py-10 lg:grid-cols-[1.15fr_400px] lg:gap-16">
          <section className="space-y-8">
            <div className="space-y-4">
              <p className="text-[11px] font-bold uppercase tracking-[0.24em] text-primary">Flaunt agency</p>
              <h1 className="font-display text-4xl font-bold leading-[1.05] tracking-tight sm:text-5xl lg:text-[3.35rem]">
                Всё для стрима
                <br />
                <span className="brand-text">в одной панели</span>
              </h1>
              <p className="max-w-xl text-base leading-relaxed text-muted-foreground">
                Викторина, команды, таймеры, розыгрыши и автоставки. Подключи игру через GSI — бот сам откроет и закроет
                predictions.
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              {highlights.map((item) => {
                const Icon = item.icon
                return (
                  <div key={item.title} className="surface-panel-sm p-4">
                    <div className="flex size-10 items-center justify-center rounded-xl bg-primary/12 text-primary">
                      <Icon className="size-5" />
                    </div>
                    <div className="mt-3 font-semibold">{item.title}</div>
                    <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{item.text}</p>
                  </div>
                )
              })}
            </div>

            <div className="hidden gap-3 lg:grid lg:grid-cols-2">
              {features.slice(3).map((item) => {
                const Icon = item.icon
                return (
                  <div key={item.title} className="flex items-center gap-3 rounded-xl border border-border/60 bg-card/40 px-4 py-3">
                    <Icon className="size-4 text-primary" />
                    <span className="text-sm font-medium">{item.title}</span>
                  </div>
                )
              })}
            </div>
          </section>

          <Card className="border-primary/20 shadow-2xl">
            <CardHeader className="space-y-4">
              <div className="brand-mark flex size-12 items-center justify-center rounded-2xl">
                <Sparkles className="size-5" />
              </div>
              <div>
                <CardTitle className="text-2xl">Войти через Twitch</CardTitle>
                <CardDescription>Нужны права владельца или модератора канала.</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
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

              <p className="text-center text-xs leading-relaxed text-muted-foreground">
                После входа откроется дашборд. Каналы модератора — в переключателе внизу сайдбара.
              </p>
            </CardContent>
          </Card>
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-border/50 pt-6 text-xs text-muted-foreground">
          <span>Установка игры: Win+R → команда из раздела «Автоставка»</span>
          <span className="flex items-center gap-1">
            <Radio className="size-3" />
            GSI Dota 2 · CS2
          </span>
        </footer>
      </div>
    </main>
  )
}
