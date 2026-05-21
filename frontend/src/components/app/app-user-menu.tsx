import * as DropdownMenu from "@radix-ui/react-dropdown-menu"
import { LogOut, Moon, Settings, Sparkles, Sun } from "lucide-react"
import { Link } from "react-router-dom"

import { useTheme } from "@/components/app/theme-provider"
import { Button } from "@/components/ui/button"

export function AppUserMenu({
  user,
  isAdmin,
}: {
  user: { display_name: string; login: string }
  isAdmin: boolean
}) {
  const { theme, toggleTheme } = useTheme()

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button className="flex w-full items-center justify-between rounded-xl border bg-background px-3 py-2.5 text-left shadow-sm transition-colors hover:bg-accent">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-full bg-gradient-to-br from-pink-500 via-violet-500 to-cyan-500 text-sm font-semibold text-white">
              {(user.display_name || user.login || "U").slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="truncate font-medium">{user.display_name}</div>
              <div className="truncate text-sm text-muted-foreground">@{user.login}</div>
            </div>
          </div>
          <Sparkles className="size-4 text-muted-foreground" />
        </button>
      </DropdownMenu.Trigger>

      <DropdownMenu.Portal>
        <DropdownMenu.Content
          side="right"
          align="end"
          sideOffset={12}
          className="z-50 min-w-64 rounded-xl border bg-popover p-1.5 text-popover-foreground shadow-xl"
        >
          <div className="flex items-center gap-3 rounded-lg px-3 py-2">
            <div className="flex size-10 items-center justify-center rounded-full bg-gradient-to-br from-pink-500 via-violet-500 to-cyan-500 text-sm font-semibold text-white">
              {(user.display_name || user.login || "U").slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="truncate font-medium">{user.display_name}</div>
              <div className="truncate text-sm text-muted-foreground">@{user.login}</div>
            </div>
          </div>

          <div className="my-1 h-px bg-border" />

          {isAdmin ? (
            <DropdownMenu.Item asChild>
              <Link
                to="/admin"
                className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm outline-none hover:bg-accent"
              >
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
              <span>{theme === "dark" ? "Light mode" : "Dark mode"}</span>
            </button>
          </DropdownMenu.Item>

          <div className="my-1 h-px bg-border" />

          <form action="/logout" method="post" className="w-full">
            <Button type="submit" variant="ghost" className="w-full justify-start px-3">
              <LogOut className="size-4" />
              <span>Log out</span>
            </Button>
          </form>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
