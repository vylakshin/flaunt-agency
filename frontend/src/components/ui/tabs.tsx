import { cn } from "@/lib/utils"

export function TabsList({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("inline-flex flex-wrap gap-1 rounded-lg border border-border/80 bg-muted/40 p-1", className)}
      role="tablist"
      {...props}
    />
  )
}

export function TabsTrigger({
  active,
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      className={cn(
        "rounded-md px-3.5 py-2 text-sm font-medium transition-colors",
        active ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
        className
      )}
      {...props}
    />
  )
}
