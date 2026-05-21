import * as DropdownMenu from "@radix-ui/react-dropdown-menu"
import {
  BarChart3,
  Check,
  ChevronsLeft,
  ChevronsRight,
  CircleHelp,
  Gift,
  LayoutDashboard,
  Loader2,
  LogOut,
  MessageSquareText,
  Moon,
  PanelLeft,
  Settings,
  ShieldCheck,
  Sun,
  Timer,
  Trophy,
} from "lucide-react"
import { useEffect, useState, type ComponentType } from "react"
import { Link, NavLink, Outlet, useLocation } from "react-router-dom"

import { BrandLogo } from "@/components/app/brand-logo"
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
import { cn } from "@/lib/utils"
import type { AppSession } from "@/types/app"

const mainNavItems = [
  { to: "/dashboard", label: "Дашборд", icon: LayoutDashboard },
  { to: "/quiz", label: "Викторина", icon: CircleHelp },
  { to: "/commands", label: "Команды", icon: MessageSquareText },
  { to: "/giveaways", label: "Розыгрыши", icon: Gift },
  { to: "/autobet", label: "Автоставка", icon: Trophy },
  { to: "/timers", label: "Таймеры", icon: Timer },
]

const adminNavItems = [
  { to: "/admin", label: "Админ", icon: ShieldCheck },
  { to: "/stats", label: "Статус", icon: BarChart3 },
]

export function AppFrame() {
  const { data, isLoading, setData } = useJsonQuery<AppSession>("/api/app/session")
  const location = useLocation()
  const [switchingChannelId, setSwitchingChannelId] = useState<number | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const isGiveaways = location.pathname.startsWith("/giveaways")

  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

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
        <Sidebar className={cn(collapsed ? "lg:w-[5.25rem]" : "lg:w-[17.5rem]", !mobileOpen && "max-lg:-translate-x-full max-lg:fixed")}>
          <div className="flex h-full flex-col">
            <SidebarHeader>
              <div className={cn("flex items-center", collapsed ? "justify-center" : "justify-between gap-2")}>
                <BrandLogo compact={collapsed} />
                <button
                  type="button"
                  className="hidden rounded-lg border border-border/60 p-2 text-muted-foreground transition hover:bg-accent lg:inline-flex"
                  onClick={() => setCollapsed((v) => !v)}
                  aria-label={collapsed ? "Развернуть меню" : "Свернуть меню"}
                >
                  {collapsed ? <ChevronsRight className="size-4" /> : <ChevronsLeft className="size-4" />}
                </button>
              </div>
            </SidebarHeader>

            <SidebarContent className={collapsed ? "overflow-visible px-1" : undefined}>
              <SidebarGroup>
                {!collapsed ? <SidebarGroupLabel>Меню</SidebarGroupLabel> : null}
                <SidebarMenu>
                  {mainNavItems.map((item) => (
                    <NavItem key={item.to} collapsed={collapsed} item={item} />
                  ))}
                </SidebarMenu>
              </SidebarGroup>

              {data?.is_admin ? (
                <SidebarGroup>
                  {!collapsed ? <SidebarGroupLabel>Админ</SidebarGroupLabel> : null}
                  <SidebarMenu>
                    {adminNavItems.map((item) => (
                      <NavItem key={item.to} collapsed={collapsed} item={item} />
                    ))}
                  </SidebarMenu>
                </SidebarGroup>
              ) : null}
            </SidebarContent>

            <SidebarFooter>
              {isLoading || !data ? (
                <Skeleton className="h-14 w-full rounded-xl" />
              ) : (
                <ChannelSwitcher
                  collapsed={collapsed}
                  data={data}
                  switchingChannelId={switchingChannelId}
                  onSwitch={(id) => void switchChannel(id)}
                />
              )}
            </SidebarFooter>
          </div>
        </Sidebar>

        {mobileOpen ? (
          <button
            type="button"
            className="fixed inset-0 z-30 bg-black/50 lg:hidden"
            aria-label="Закрыть меню"
            onClick={() => setMobileOpen(false)}
          />
        ) : null}

        <div className={cn("flex min-h-screen flex-1 flex-col", collapsed ? "lg:pl-[5.25rem]" : "lg:pl-[17.5rem]")}>
          <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-border/50 bg-background/75 px-4 py-3 backdrop-blur-xl lg:px-8">
            <button
              type="button"
              className="rounded-xl border border-border/70 p-2.5 text-muted-foreground lg:hidden"
              onClick={() => setMobileOpen(true)}
              aria-label="Открыть меню"
            >
              <PanelLeft className="size-5" />
            </button>
            <div className="hidden text-sm text-muted-foreground lg:block">
              {data?.active_channel.display_name || data?.active_channel.login || "Канал"}
            </div>
            <div className="ml-auto flex items-center gap-2">
              {data?.is_admin ? (
                <Link
                  to="/admin"
                  className="hidden rounded-xl border border-border/70 px-3 py-2 text-xs font-semibold text-muted-foreground transition hover:text-foreground sm:inline-flex"
                >
                  Админ
                </Link>
              ) : null}
            </div>
          </header>

          <main className={cn("flex-1 px-4 py-6 lg:px-8 lg:py-8", isGiveaways && "px-3 lg:px-5")}>
            <div className={cn(isGiveaways ? "mx-auto w-full max-w-[90rem]" : "mx-auto w-full max-w-7xl")}>
              <Outlet key={data?.active_channel.id ?? "loading"} />
            </div>
          </main>
        </div>
      </SidebarProvider>
    </ThemeProvider>
  )
}

function NavItem({
  collapsed,
  item,
}: {
  collapsed: boolean
  item: { to: string; label: string; icon: ComponentType<{ className?: string }> }
}) {
  const Icon = item.icon
  return (
    <SidebarMenuItem>
      <NavLink
        to={item.to}
        title={collapsed ? item.label : undefined}
        className={({ isActive }) =>
          cn(sidebarMenuButtonVariants({ isActive }), collapsed && "justify-center px-0 pl-0", !collapsed && "pl-4")
        }
      >
        <Icon className="size-4 shrink-0" />
        {!collapsed ? <span>{item.label}</span> : null}
      </NavLink>
    </SidebarMenuItem>
  )
}

function ChannelSwitcher({
  collapsed,
  data,
  onSwitch,
  switchingChannelId,
}: {
  collapsed: boolean
  data: AppSession
  onSwitch: (ownerId: number) => void
  switchingChannelId: number | null
}) {
  const active = data.active_channel
  const { theme, toggleTheme } = useTheme()

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          className={cn(
            "flex w-full items-center gap-3 rounded-xl border border-border/60 bg-card/50 p-2.5 text-left transition hover:border-primary/35 hover:bg-accent/60",
            collapsed && "justify-center p-2"
          )}
        >
          <ChannelAvatar label={active.display_name || active.login} src={active.profile_image_url} />
          {!collapsed ? (
            <>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold">{active.display_name || active.login}</span>
                <span className="block truncate text-xs text-muted-foreground">Сменить канал</span>
              </span>
              {switchingChannelId ? (
                <Loader2 className="size-4 animate-spin text-muted-foreground" />
              ) : (
                <ChevronsRight className="size-4 text-muted-foreground" />
              )}
            </>
          ) : null}
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          side="top"
          align={collapsed ? "center" : "start"}
          sideOffset={8}
          className="z-50 w-[min(20rem,calc(100vw-1.5rem))] rounded-2xl border border-border/80 bg-popover/95 p-1.5 shadow-2xl backdrop-blur-xl"
        >
          <p className="px-3 py-2 text-[10px] font-bold uppercase tracking-[0.2em] text-muted-foreground">Каналы</p>
          {data.channels.map((channel) => (
            <DropdownMenu.Item asChild key={channel.id}>
              <button
                type="button"
                className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm outline-none hover:bg-accent disabled:opacity-60"
                onClick={() => onSwitch(channel.id)}
                disabled={switchingChannelId !== null}
              >
                <ChannelAvatar label={channel.display_name || channel.login} src={channel.profile_image_url} small />
                <span className="min-w-0 flex-1 truncate font-medium">{channel.display_name || channel.login}</span>
                {channel.role === "owner" ? <Badge variant="brand">Я</Badge> : null}
                {channel.is_active ? <Check className="size-4 text-primary" /> : null}
              </button>
            </DropdownMenu.Item>
          ))}
          <div className="my-1 h-px bg-border/60" />
          <DropdownMenu.Item asChild>
            <button type="button" onClick={toggleTheme} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm hover:bg-accent">
              {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
              {theme === "dark" ? "Светлая тема" : "Тёмная тема"}
            </button>
          </DropdownMenu.Item>
          {data.is_admin ? (
            <DropdownMenu.Item asChild>
              <Link to="/admin" className="flex items-center gap-3 rounded-xl px-3 py-2 text-sm hover:bg-accent">
                <Settings className="size-4" />
                Настройки
              </Link>
            </DropdownMenu.Item>
          ) : null}
          <div className="my-1 h-px bg-border/60" />
          <form action="/logout" method="post">
            <button type="submit" className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm hover:bg-accent">
              <LogOut className="size-4" />
              Выйти
            </button>
          </form>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

function ChannelAvatar({ label, src, small }: { label: string; src?: string; small?: boolean }) {
  const initial = (label || "U").slice(0, 1).toUpperCase()
  const size = small ? "size-8" : "size-10"
  if (src) {
    return <img alt="" className={cn(size, "shrink-0 rounded-full object-cover ring-2 ring-border/50")} src={src} />
  }
  return (
    <div className={cn("brand-mark flex shrink-0 items-center justify-center rounded-full text-sm font-bold", size)}>
      {initial}
    </div>
  )
}
