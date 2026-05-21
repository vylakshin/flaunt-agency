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
import { useTheme } from "@/components/app/theme-provider"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
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
  { to: "/stats", label: "Системы", icon: BarChart3 },
]

const routeTitles: Record<string, string> = {
  "/dashboard": "Дашборд",
  "/quiz": "Викторина",
  "/commands": "Команды",
  "/giveaways": "Розыгрыши",
  "/autobet": "Автоставка",
  "/timers": "Таймеры",
  "/admin": "Админ",
  "/stats": "Системы",
}

export function AppFrame() {
  const { data, isLoading, setData } = useJsonQuery<AppSession>("/api/app/session")
  const location = useLocation()
  const [switchingChannelId, setSwitchingChannelId] = useState<number | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)

  const pageTitle = routeTitles[location.pathname] ?? "Flaunt"

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
    <SidebarProvider>
      <Sidebar
        className={cn(
          "sidebar-panel transition-[width,transform] duration-200",
          collapsed ? "lg:w-[4.25rem]" : "lg:w-[15rem]",
          !mobileOpen && "max-lg:-translate-x-full max-lg:fixed"
        )}
      >
        <div className="flex h-full flex-col">
          <SidebarHeader className="border-sidebar-border">
            <div className={cn("flex items-center", collapsed ? "justify-center" : "justify-between gap-2")}>
              <BrandLogo compact={collapsed} />
              <button
                type="button"
                className="hidden rounded-md border border-sidebar-border p-2 text-muted-foreground transition hover:bg-sidebar-accent lg:inline-flex"
                onClick={() => setCollapsed((v) => !v)}
                aria-label={collapsed ? "Развернуть меню" : "Свернуть меню"}
              >
                {collapsed ? <ChevronsRight className="size-4" /> : <ChevronsLeft className="size-4" />}
              </button>
            </div>
          </SidebarHeader>

          <SidebarContent className={collapsed ? "overflow-visible px-1.5" : undefined}>
            <SidebarGroup>
              {!collapsed ? <SidebarGroupLabel>Модули</SidebarGroupLabel> : null}
              <SidebarMenu>
                {mainNavItems.map((item) => (
                  <NavItem key={item.to} collapsed={collapsed} item={item} />
                ))}
              </SidebarMenu>
            </SidebarGroup>

            {data?.is_admin ? (
              <SidebarGroup>
                {!collapsed ? <SidebarGroupLabel>Служебное</SidebarGroupLabel> : null}
                <SidebarMenu>
                  {adminNavItems.map((item) => (
                    <NavItem key={item.to} collapsed={collapsed} item={item} />
                  ))}
                </SidebarMenu>
              </SidebarGroup>
            ) : null}
          </SidebarContent>

          <SidebarFooter className="border-sidebar-border">
            {isLoading || !data ? (
              <Skeleton className="h-11 w-full rounded-md" />
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
          className="fixed inset-0 z-30 bg-black/60 lg:hidden"
          aria-label="Закрыть меню"
          onClick={() => setMobileOpen(false)}
        />
      ) : null}

      <div className={cn("flex min-h-screen flex-1 flex-col bg-background", collapsed ? "lg:pl-[4.25rem]" : "lg:pl-[15rem]")}>
        <header className="sticky top-0 z-20 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/80 lg:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              className="rounded-md border border-border p-2 text-muted-foreground lg:hidden"
              onClick={() => setMobileOpen(true)}
              aria-label="Открыть меню"
            >
              <PanelLeft className="size-5" />
            </button>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold">{pageTitle}</div>
              <div className="truncate text-xs text-muted-foreground">
                {data?.active_channel.display_name || data?.active_channel.login || "…"}
              </div>
            </div>
          </div>

          {data ? (
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="hidden font-normal normal-case tracking-normal sm:inline-flex">
                @{data.active_channel.login}
              </Badge>
              <ChannelAvatar label={data.active_channel.display_name || data.active_channel.login} src={data.active_channel.profile_image_url} />
            </div>
          ) : null}
        </header>

        <main className="flex-1 px-4 py-6 lg:px-8 lg:py-8">
          <Outlet key={data?.active_channel.id ?? "loading"} />
        </main>
      </div>
    </SidebarProvider>
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
          cn(sidebarMenuButtonVariants({ isActive }), collapsed && "justify-center px-2", !collapsed && "pl-3")
        }
      >
        <Icon className="size-[18px] shrink-0 opacity-90" />
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
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(
            "flex w-full items-center gap-2.5 rounded-md border border-sidebar-border bg-sidebar-accent/50 p-2 text-left text-sm transition hover:bg-sidebar-accent",
            collapsed && "justify-center p-2"
          )}
        >
          <ChannelAvatar label={active.display_name || active.login} src={active.profile_image_url} />
          {!collapsed ? (
            <>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{active.display_name || active.login}</span>
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
      </DropdownMenuTrigger>

      <DropdownMenuContent side="top" align={collapsed ? "center" : "start"} className="w-72">
        <DropdownMenuLabel>Каналы</DropdownMenuLabel>
        {data.channels.map((channel) => (
          <DropdownMenuItem
            key={channel.id}
            className="gap-2.5"
            disabled={switchingChannelId !== null}
            onClick={() => onSwitch(channel.id)}
          >
            <ChannelAvatar label={channel.display_name || channel.login} src={channel.profile_image_url} small />
            <span className="min-w-0 flex-1 truncate">{channel.display_name || channel.login}</span>
            {channel.role === "owner" ? <Badge variant="brand">Я</Badge> : null}
            {channel.is_active ? <Check className="size-4 text-primary" /> : null}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={toggleTheme}>
          {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
          {theme === "dark" ? "Светлая тема" : "Тёмная тема"}
        </DropdownMenuItem>
        {data.is_admin ? (
          <DropdownMenuItem asChild>
            <Link to="/admin" className="flex items-center gap-2">
              <Settings className="size-4" />
              Админ
            </Link>
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuSeparator />
        <form action="/logout" method="post" className="w-full">
          <button type="submit" className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent">
            <LogOut className="size-4" />
            Выйти
          </button>
        </form>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function ChannelAvatar({ label, src, small }: { label: string; src?: string; small?: boolean }) {
  const initial = (label || "U").slice(0, 1).toUpperCase()
  const size = small ? "size-7" : "size-8"

  return (
    <Avatar className={cn(size, "shrink-0")}>
      {src ? <AvatarImage src={src} alt="" /> : null}
      <AvatarFallback className="brand-mark text-[10px] font-bold text-white">{initial}</AvatarFallback>
    </Avatar>
  )
}
