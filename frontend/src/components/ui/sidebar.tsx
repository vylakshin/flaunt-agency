import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

export function SidebarProvider({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("app-canvas flex min-h-screen w-full flex-col lg:flex-row", className)} {...props} />
}

export function Sidebar({ className, ...props }: React.HTMLAttributes<HTMLElement>) {
  return (
    <aside
      className={cn(
        "sidebar-panel z-40 border-b text-card-foreground lg:fixed lg:inset-y-0 lg:left-0 lg:w-[17.5rem] lg:border-b-0 lg:border-r",
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
  return <div className={cn("flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-3", className)} {...props} />
}

export function SidebarFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("border-t border-border/50 p-3", className)} {...props} />
}

export function SidebarGroup({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("space-y-1.5", className)} {...props} />
}

export function SidebarGroupLabel({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("px-3 pb-1 text-[10px] font-bold uppercase tracking-[0.22em] text-muted-foreground/90", className)}
      {...props}
    />
  )
}

export function SidebarMenu({ className, ...props }: React.HTMLAttributes<HTMLUListElement>) {
  return <ul className={cn("space-y-0.5", className)} {...props} />
}

export function SidebarMenuItem({ className, ...props }: React.LiHTMLAttributes<HTMLLIElement>) {
  return <li className={cn("list-none", className)} {...props} />
}

export const sidebarMenuButtonVariants = cva("nav-pill w-full pl-4", {
  variants: {
    isActive: {
      true: "nav-pill-active",
      false: "nav-pill-idle",
    },
  },
  defaultVariants: {
    isActive: false,
  },
})

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
