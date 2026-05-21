import { Bot, LogIn, Radio, ShieldCheck, Sparkles } from "lucide-react"
import { useEffect, useMemo } from "react"
import { useSearchParams } from "react-router-dom"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"

export function LoginPage() {
  const [params] = useSearchParams()
  const error = params.get("error") || ""
  const warning = params.get("warning") || ""

  useEffect(() => {
    document.title = "QUUUIZBOT — вход"
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
    <main className="min-h-screen bg-background px-4 py-6 text-foreground sm:px-6 lg:px-8">
      <div className="mx-auto flex min-h-[calc(100vh-3rem)] w-full max-w-6xl flex-col">
        <header className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-primary text-sm font-semibold text-primary-foreground">
              QB
            </div>
            <div>
              <div className="text-xs font-semibold uppercase tracking-[0.22em] text-muted-foreground">QUUUIZBOT</div>
              <div className="font-semibold">Панель управления</div>
            </div>
          </div>
        </header>

        <section className="grid flex-1 items-center gap-8 py-10 lg:grid-cols-[1fr_420px]">
          <div className="max-w-2xl space-y-6">
            <Badge variant="outline">Twitch-бот</Badge>
            <div className="space-y-4">
              <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">Управляй ботом без лишних вкладок.</h1>
              <p className="max-w-xl text-base leading-7 text-muted-foreground">
                Команды, таймеры, викторина, розыгрыши и доступы модераторов собраны в одной панели.
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              {statusCards.map((item) => {
                const Icon = item.icon
                return (
                  <Card key={item.label}>
                    <CardContent className="space-y-3 p-4">
                      <div className="flex size-10 items-center justify-center rounded-lg bg-secondary text-secondary-foreground">
                        <Icon className="size-5" />
                      </div>
                      <div>
                        <div className="font-medium">{item.label}</div>
                        <div className="mt-1 text-sm text-muted-foreground">{item.value}</div>
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          </div>

          <Card className="w-full shadow-xl">
            <CardHeader className="space-y-3">
              <div className="flex size-12 items-center justify-center rounded-xl bg-primary text-primary-foreground">
                <Sparkles className="size-5" />
              </div>
              <div>
                <CardTitle className="text-2xl">Вход через Twitch</CardTitle>
                <CardDescription>Авторизация нужна, чтобы привязать канал и проверить доступ к управлению.</CardDescription>
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

              <Button asChild className="h-12 w-full text-base">
                <a href="/auth/twitch/login">
                  <LogIn className="size-5" />
                  Войти через Twitch
                </a>
              </Button>

              <p className="text-center text-xs leading-5 text-muted-foreground">
                После входа откроется дашборд выбранного канала. Если ты модератор другого канала, он появится в переключателе снизу сайдбара.
              </p>
            </CardContent>
          </Card>
        </section>
      </div>
    </main>
  )
}
