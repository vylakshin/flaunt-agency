import type { HTMLAttributes } from "react"

import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva("inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide", {
  variants: {
    variant: {
      default: "bg-secondary text-secondary-foreground",
      brand: "border border-primary/30 bg-primary/12 text-primary",
      success: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
      warning: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
      destructive: "bg-destructive/15 text-destructive",
      outline: "border border-border/90 bg-transparent text-foreground",
    },
  },
  defaultVariants: {
    variant: "default",
  },
})

export function Badge({
  className,
  variant,
  ...props
}: HTMLAttributes<HTMLDivElement> & VariantProps<typeof badgeVariants>) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />
}
