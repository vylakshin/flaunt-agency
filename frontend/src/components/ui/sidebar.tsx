import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

export function SidebarProvider({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex min-h-screen w-full flex-col bg-background lg:flex-row", className)} {...props} />
}

export function Sidebar({ className, ...props }: React.HTMLAttributes<HTMLElement>) {
  return (
    <aside
      className={cn(
        "sidebar-glass border-b border-border/60 text-card-foreground lg:fixed lg:inset-y-0 lg:left-0 lg:z-30 lg:w-72 lg:border-b-0 lg:border-r",
        className
      )}
      {...props}
    />
  )
}

export function SidebarHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("border-b border-border/50 p-4", className)} {...props} />
}

export function SidebarContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-3", className)} {...props} />
}

export function SidebarFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("border-t border-border/50 p-3", className)} {...props} />
}

export function SidebarGroup({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("space-y-2", className)} {...props} />
}

export function SidebarGroupLabel({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("px-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-muted-foreground/80", className)}
      {...props}
    />
  )
}

export function SidebarMenu({ className, ...props }: React.HTMLAttributes<HTMLUListElement>) {
  return <ul className={cn("space-y-1", className)} {...props} />
}

export function SidebarMenuItem({ className, ...props }: React.LiHTMLAttributes<HTMLLIElement>) {
  return <li className={cn("list-none", className)} {...props} />
}

export const sidebarMenuButtonVariants = cva(
  "relative flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium outline-none transition-all duration-200 focus-visible:ring-2 focus-visible:ring-ring",
  {
    variants: {
      isActive: {
        true: "bg-primary/12 text-foreground shadow-[inset_0_0_0_1px] shadow-primary/20 before:absolute before:left-0 before:top-1/2 before:h-6 before:w-1 before:-translate-y-1/2 before:rounded-full before:bg-primary",
        false: "text-muted-foreground hover:bg-accent/80 hover:text-foreground",
      },
    },
    defaultVariants: {
      isActive: false,
    },
  }
)

export function SidebarMenuButton({
  asChild = false,
  className,
  isActive,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof sidebarMenuButtonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot : "button"
  return <Comp className={cn(sidebarMenuButtonVariants({ isActive }), className)} {...props} />
}
