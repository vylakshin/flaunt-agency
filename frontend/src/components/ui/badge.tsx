import type { HTMLAttributes } from "react"

import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const badgeVariants = cva("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold", {
  variants: {
    variant: {
      default: "bg-secondary text-secondary-foreground",
      brand: "border border-primary/25 bg-primary/10 text-primary",
      success: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
      destructive: "bg-destructive/15 text-destructive",
      outline: "border border-border/80 bg-transparent text-foreground",
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
