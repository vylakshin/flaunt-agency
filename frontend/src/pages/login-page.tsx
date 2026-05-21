import { Bot, CircleHelp, LogIn, MessageSquareText, Radio, ShieldCheck, Sparkles, Timer, Trophy } from "lucide-react"
import { useEffect, useMemo } from "react"
import { useSearchParams } from "react-router-dom"

import { BrandLogo } from "@/components/app/brand-logo"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

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
    <main className="login-stage">
      <div className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-4 py-8 sm:px-8">
        <header className="flex items-center justify-between">
          <BrandLogo subtitle="Панель стримера" />
        </header>

        <div className="grid flex-1 items-center gap-12 py-12 lg:grid-cols-[1.15fr_400px] lg:gap-16">
          <section className="space-y-8">
            <div className="space-y-4">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">Flaunt Bot</p>
              <h1 className="text-4xl font-bold leading-[1.08] tracking-tight sm:text-5xl">
                Управление каналом
                <br />
                <span className="brand-text">как в StreamElements</span>
              </h1>
              <p className="max-w-lg text-base leading-relaxed text-muted-foreground">
                Викторина, команды, таймеры, розыгрыши и автоставки. Один дашборд — подключи бота и настрой модули за минуты.
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              {highlights.map((item) => {
                const Icon = item.icon
                return (
                  <Card key={item.title} className="py-4 shadow-none">
                    <CardContent className="px-4">
                      <Icon className="size-5 text-primary" />
                      <div className="mt-3 font-semibold">{item.title}</div>
                      <p className="mt-1 text-xs text-muted-foreground">{item.text}</p>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          </section>

          <Card className="shadow-lg">
            <CardHeader>
              <div className="brand-mark mb-1 flex size-11 items-center justify-center rounded-lg">
                <Sparkles className="size-5 text-white" />
              </div>
              <CardTitle>Войти через Twitch</CardTitle>
              <CardDescription>Нужны права владельца или модератора канала.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
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
            </CardContent>
          </Card>
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
  )
}
