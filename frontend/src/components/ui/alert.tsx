import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const alertVariants = cva("relative w-full rounded-xl border p-4 text-sm backdrop-blur-sm", {
  variants: {
    variant: {
      default: "border-border bg-card text-card-foreground",
      success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
      warning: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
      destructive: "border-destructive/30 bg-destructive/10 text-destructive",
    },
  },
  defaultVariants: {
    variant: "default",
  },
})

export function Alert({
  className,
  variant,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>) {
  return <div className={cn(alertVariants({ variant }), className)} role="alert" {...props} />
}

export function AlertTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h5 className={cn("mb-1 font-medium leading-none tracking-tight", className)} {...props} />
}

export function AlertDescription({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("text-sm leading-relaxed opacity-90", className)} {...props} />
}
