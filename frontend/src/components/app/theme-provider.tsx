import { ThemeProvider as NextThemesProvider, useTheme as useNextTheme } from "next-themes"
import type { ReactNode } from "react"

type Theme = "light" | "dark"

export function ThemeProvider({ children }: { children: ReactNode }) {
  return (
    <NextThemesProvider attribute="class" defaultTheme="dark" enableSystem={false} storageKey="site-theme">
      {children}
    </NextThemesProvider>
  )
}

export function useTheme() {
  const { theme, setTheme, resolvedTheme } = useNextTheme()
  const active = (resolvedTheme ?? theme ?? "dark") as Theme

  return {
    theme: active,
    toggleTheme: () => setTheme(active === "dark" ? "light" : "dark"),
  }
}
