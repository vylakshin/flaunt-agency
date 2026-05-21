import * as DropdownMenu from "@radix-ui/react-dropdown-menu"
import {
  BarChart3,
  Check,
  ChevronsUpDown,
  CircleHelp,
  Gift,
  LayoutDashboard,
  Loader2,
  LogOut,
  MessageSquareText,
  Moon,
  Settings,
  ShieldCheck,
  Sun,
  Timer,
  Trophy,
} from "lucide-react"
import { useEffect, useState, type ComponentType } from "react"
import { Link, NavLink, Outlet, useLocation } from "react-router-dom"

import { ThemeProvider, useTheme } from "@/components/app/theme-provider"
import { Badge } from "@/components/ui/badge"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuItem,
  SidebarProvider,
  sidebarMenuButtonVariants,
} from "@/components/ui/sidebar"
import { Skeleton } from "@/components/ui/skeleton"
import { useJsonQuery } from "@/hooks/use-json-query"
import { requestJson } from "@/lib/api"
import type { AppSession } from "@/types/app"

const mainNavItems = [
  { to: "/dashboard", label: "Дашборд", icon: LayoutDashboard, ownerOnly: false },
  { to: "/quiz", label: "Викторина", icon: CircleHelp, ownerOnly: false },
  { to: "/commands", label: "Команды", icon: MessageSquareText, ownerOnly: false },
  { to: "/giveaways", label: "Розыгрыши", icon: Gift, ownerOnly: false },
  { to: "/autobet", label: "Автоставка", icon: Trophy, ownerOnly: false },
  { to: "/timers", label: "Таймеры", icon: Timer, ownerOnly: false },
]

const adminNavItems = [
  { to: "/admin", label: "Админ-панель", icon: ShieldCheck },
  { to: "/stats", label: "Статистика", icon: BarChart3 },
]

export function AppFrame() {
  const { data, isLoading, setData } = useJsonQuery<AppSession>("/api/app/session")
  const location = useLocation()
  const [switchingChannelId, setSwitchingChannelId] = useState<number | null>(null)
  const [isSidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [isMobile, setIsMobile] = useState(false)
  const isGiveawaysPage = location.pathname.startsWith("/giveaways")
  const visibleMainItems = mainNavItems.filter((item) => !item.ownerOnly || data?.active_channel.role === "owner")

  useEffect(() => {
    const updateIsMobile = () => setIsMobile(window.innerWidth < 1024)
    updateIsMobile()
    window.addEventListener("resize", updateIsMobile)
    return () => window.removeEventListener("resize", updateIsMobile)
  }, [])

  async function switchChannel(ownerId: number) {
    if (!data || ownerId === data.active_channel.id) return
    setSwitchingChannelId(ownerId)
    try {
      const nextSession = await requestJson<AppSession>("/api/app/session/channel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ owner_id: ownerId }),
      })
      setData(nextSession)
    } finally {
      setSwitchingChannelId(null)
    }
  }

  return (
    <ThemeProvider>
      <SidebarProvider>
        <Sidebar className={isSidebarCollapsed ? "lg:w-20" : "lg:w-72"}>
          <div className="flex h-full flex-col">
            <SidebarHeader>
              <div className={isSidebarCollapsed ? "flex items-center justify-center" : "flex items-center gap-3"}>
                <div className="flex size-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  QB
                </div>
                <div className={isSidebarCollapsed ? "hidden" : "min-w-0"}>
                  <div className="text-xs font-semibold uppercase tracking-[0.22em] text-muted-foreground">QUUUIZBOT</div>
                  <div className="truncate font-semibold">Панель управления</div>
                </div>
              </div>
              <button
                type="button"
                className="mt-3 hidden w-full items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground lg:flex"
                onClick={() => setSidebarCollapsed((value) => !value)}
                aria-label={isSidebarCollapsed ? "Развернуть сайдбар" : "Свернуть сайдбар"}
                title={isSidebarCollapsed ? "Развернуть" : "Свернуть"}
              >
                <ChevronsUpDown className={isSidebarCollapsed ? "size-4 rotate-90" : "size-4 -rotate-90"} />
                <span className={isSidebarCollapsed ? "hidden" : ""}>{isSidebarCollapsed ? "Развернуть" : "Свернуть"}</span>
              </button>
            </SidebarHeader>

            <SidebarContent className={isSidebarCollapsed ? "overflow-visible" : undefined}>
              <SidebarGroup>
                <SidebarGroupLabel className={isSidebarCollapsed ? "sr-only" : ""}>Навигация</SidebarGroupLabel>
                <SidebarMenu>
                  {visibleMainItems.map((item) => (
                    <NavMenuLink key={item.to} collapsed={isSidebarCollapsed} item={item} />
                  ))}
                </SidebarMenu>
              </SidebarGroup>

              {data?.is_admin ? (
                <SidebarGroup>
                  <SidebarGroupLabel className={isSidebarCollapsed ? "sr-only" : ""}>Админ-панель</SidebarGroupLabel>
                  <SidebarMenu>
                    {adminNavItems.map((item) => (
                      <NavMenuLink key={item.to} collapsed={isSidebarCollapsed} item={item} />
                    ))}
                  </SidebarMenu>
                </SidebarGroup>
              ) : null}
            </SidebarContent>

            <SidebarFooter>
              {isLoading || !data ? (
                <Skeleton className="h-16 w-full" />
              ) : (
                <ChannelMenu
                  collapsed={isSidebarCollapsed}
                  data={data}
                  isMobile={isMobile}
                  switchingChannelId={switchingChannelId}
                  onSwitch={(ownerId) => void switchChannel(ownerId)}
                />
              )}
            </SidebarFooter>
          </div>
        </Sidebar>

        <main className={isSidebarCollapsed ? "flex-1 lg:ml-20" : "flex-1 lg:ml-72"}>
          <div className={isGiveawaysPage ? "mx-auto flex min-h-screen w-full max-w-none flex-col gap-6 p-4 lg:p-6" : "mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-6 p-4 lg:p-8"}>
            <Outlet key={data?.active_channel.id ?? "loading"} />
          </div>
        </main>
      </SidebarProvider>
    </ThemeProvider>
  )
}

function ChannelMenu({
  collapsed,
  data,
  isMobile,
  onSwitch,
  switchingChannelId,
}: {
  collapsed: boolean
  data: AppSession
  isMobile: boolean
  onSwitch: (ownerId: number) => void
  switchingChannelId: number | null
}) {
  const active = data.active_channel
  const { theme, toggleTheme } = useTheme()

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          className={collapsed ? "group relative flex w-full items-center justify-center rounded-xl border bg-background p-2 text-left shadow-sm transition-colors hover:bg-accent" : "flex w-full items-center justify-between gap-3 rounded-xl border bg-background px-3 py-2.5 text-left shadow-sm transition-colors hover:bg-accent"}
          title={collapsed ? `${active.display_name || active.login} · управление` : undefined}
          type="button"
        >
          <div className="flex min-w-0 items-center gap-3">
            <ChannelAvatar label={active.display_name || active.login} src={active.profile_image_url} />
            <div className={collapsed ? "hidden" : "min-w-0"}>
              <div className="truncate font-medium">{active.display_name || active.login}</div>
              <div className="truncate text-sm text-muted-foreground">Управление</div>
            </div>
          </div>
          {collapsed ? (
            <CollapsedTooltip label={`${active.display_name || active.login} · управление`} />
          ) : switchingChannelId ? (
            <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" />
          ) : (
            <ChevronsUpDown className="size-4 shrink-0 text-muted-foreground" />
          )}
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          side={isMobile ? "bottom" : "right"}
          align="end"
          sideOffset={isMobile ? 8 : 12}
          collisionPadding={12}
          className="z-50 w-[min(22rem,calc(100vw-1.5rem))] rounded-xl border bg-popover p-1.5 text-popover-foreground shadow-xl"
        >
          <div className="px-3 py-2 text-xs font-medium uppercase tracking-[0.16em] text-muted-foreground">Доступные каналы</div>

          {data.channels.map((channel) => (
            <DropdownMenu.Item asChild key={channel.id}>
              <button
                type="button"
                className="flex w-full cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm outline-none hover:bg-accent disabled:cursor-default disabled:opacity-70"
                onClick={() => onSwitch(channel.id)}
                disabled={switchingChannelId !== null}
              >
                <ChannelAvatar label={channel.display_name || channel.login} src={channel.profile_image_url} />
                <span className="min-w-0 flex-1">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="truncate font-medium">{channel.display_name || channel.login}</span>
                    {channel.role === "owner" ? <Badge className="px-1.5 py-0 text-[10px] uppercase">Я</Badge> : null}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">twitch.tv/{channel.login}</span>
                </span>
                {switchingChannelId === channel.id ? (
                  <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" />
                ) : channel.is_active ? (
                  <Check className="size-4 shrink-0 text-primary" />
                ) : null}
              </button>
            </DropdownMenu.Item>
          ))}

          <div className="my-1 h-px bg-border" />

          {data.is_admin ? (
            <DropdownMenu.Item asChild>
              <Link to="/admin" className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm outline-none hover:bg-accent">
                <Settings className="size-4" />
                <span>Админ-панель</span>
              </Link>
            </DropdownMenu.Item>
          ) : null}

          <DropdownMenu.Item asChild>
            <button
              type="button"
              onClick={toggleTheme}
              className="flex w-full cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-left text-sm outline-none hover:bg-accent"
            >
              {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
              <span>{theme === "dark" ? "Светлая тема" : "Тёмная тема"}</span>
            </button>
          </DropdownMenu.Item>

          <div className="my-1 h-px bg-border" />

          <form action="/logout" method="post" className="w-full">
            <button
              type="submit"
              className="flex w-full cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-left text-sm outline-none hover:bg-accent"
            >
              <LogOut className="size-4" />
              <span>Выйти</span>
            </button>
          </form>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

function NavMenuLink({
  collapsed,
  item,
}: {
  collapsed: boolean
  item: {
    to: string
    label: string
    icon: ComponentType<{ className?: string }>
  }
}) {
  const Icon = item.icon

  return (
    <SidebarMenuItem>
      <NavLink
        to={item.to}
        title={collapsed ? item.label : undefined}
        aria-label={item.label}
        className={({ isActive }) =>
          [
            sidebarMenuButtonVariants({ isActive }),
            collapsed ? "group relative justify-center px-0" : "",
          ].filter(Boolean).join(" ")
        }
      >
        <Icon className="size-4 shrink-0" />
        <span className={collapsed ? "sr-only" : ""}>{item.label}</span>
        {collapsed ? <CollapsedTooltip label={item.label} /> : null}
      </NavLink>
    </SidebarMenuItem>
  )
}

function CollapsedTooltip({ label }: { label: string }) {
  return (
    <span className="pointer-events-none absolute left-full top-1/2 z-50 ml-3 hidden -translate-y-1/2 whitespace-nowrap rounded-md border bg-popover px-2.5 py-1.5 text-xs font-medium text-popover-foreground shadow-lg group-hover:block">
      {label}
    </span>
  )
}

function ChannelAvatar({ label, src }: { label: string; src?: string }) {
  const initial = (label || "U").slice(0, 1).toUpperCase()

  if (src) {
    return <img alt="" className="size-10 shrink-0 rounded-full object-cover" src={src} />
  }

  return (
    <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-pink-500 via-violet-500 to-cyan-500 text-sm font-semibold text-white">
      {initial}
    </div>
  )
}
