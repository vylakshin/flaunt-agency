import { Bot, LogIn, Radio, ShieldCheck, Sparkles, Zap } from "lucide-react"
import { useEffect, useMemo } from "react"
import { useSearchParams } from "react-router-dom"

import { BrandLogo } from "@/components/app/brand-logo"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export function LoginPage() {
  const [params] = useSearchParams()
  const error = params.get("error") || ""
  const warning = params.get("warning") || ""

  useEffect(() => {
    document.title = "Flaunt — вход"
  }, [])

  const statusCards = useMemo(
    () => [
      { icon: Bot, label: "Бот", value: "Команды, таймеры и розыгрыши" },
      { icon: Radio, label: "Чат", value: "Twitch EventSub без перезагрузок" },
      { icon: ShieldCheck, label: "Доступ", value: "Свой канал и модераторские роли" },
    ],
    []
  )

  return (
    <main className="login-mesh min-h-screen px-4 py-6 text-foreground sm:px-6 lg:px-8">
      <div className="mx-auto flex min-h-[calc(100vh-3rem)] w-full max-w-6xl flex-col">
        <header className="flex items-center justify-between gap-4">
          <BrandLogo />
          <Badge variant="brand" className="hidden gap-1.5 sm:inline-flex">
            <Zap className="size-3" />
            Twitch-инструменты
          </Badge>
        </header>

        <section className="grid flex-1 items-center gap-10 py-10 lg:grid-cols-[1.1fr_420px] lg:gap-14">
          <div className="max-w-2xl space-y-8">
            <div className="space-y-4">
              <Badge variant="outline">Всё для стрима в одном месте</Badge>
              <h1 className="font-display text-4xl font-bold leading-[1.08] tracking-tight sm:text-5xl lg:text-[3.25rem]">
                Управляй каналом <span className="brand-gradient-text">без хаоса</span>
              </h1>
              <p className="max-w-xl text-base leading-7 text-muted-foreground">
                Викторина, команды, розыгрыши, автоставки и таймеры — единая панель с быстрым доступом и понятной
                структурой.
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              {statusCards.map((item) => {
                const Icon = item.icon
                return (
                  <Card key={item.label} className="border-border/60 bg-card/70">
                    <CardContent className="space-y-3 p-4">
                      <div className="flex size-10 items-center justify-center rounded-xl bg-primary/10 text-primary">
                        <Icon className="size-5" />
                      </div>
                      <div>
                        <div className="font-semibold">{item.label}</div>
                        <div className="mt-1 text-sm leading-relaxed text-muted-foreground">{item.value}</div>
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          </div>

          <Card className="border-border/70 bg-card/80 shadow-2xl backdrop-blur-xl">
            <CardHeader className="space-y-4">
              <div className="brand-gradient flex size-12 items-center justify-center rounded-2xl text-white shadow-lg">
                <Sparkles className="size-5" />
              </div>
              <div>
                <CardTitle className="text-2xl">Вход через Twitch</CardTitle>
                <CardDescription>
                  Авторизация нужна, чтобы привязать канал и проверить права владельца или модератора.
                </CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {error ? (
                <Alert variant="destructive">
                  <AlertTitle>Войти не получилось</AlertTitle>
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              ) : null}
              {warning ? (
                <Alert variant="warning">
                  <AlertTitle>Проверь вход</AlertTitle>
                  <AlertDescription>{warning}</AlertDescription>
                </Alert>
              ) : null}

              <Button asChild variant="brand" size="lg" className="w-full">
                <a href="/auth/twitch/login">
                  <LogIn className="size-5" />
                  Войти через Twitch
                </a>
              </Button>

              <p className="text-center text-xs leading-5 text-muted-foreground">
                После входа откроется дашборд выбранного канала. Каналы модератора доступны в переключателе внизу
                сайдбара.
              </p>
            </CardContent>
          </Card>
        </section>
      </div>
    </main>
  )
}
