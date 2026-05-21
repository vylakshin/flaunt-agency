import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

const alertVariants = cva("relative w-full rounded-2xl border p-4 text-sm backdrop-blur-md", {
  variants: {
    variant: {
      default: "border-border/80 bg-card/80 text-card-foreground",
      success: "border-emerald-500/35 bg-emerald-500/10 text-emerald-800 dark:text-emerald-200",
      warning: "border-amber-500/35 bg-amber-500/10 text-amber-900 dark:text-amber-100",
      destructive: "border-destructive/35 bg-destructive/10 text-destructive",
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
  return <h5 className={cn("mb-1 font-display font-semibold leading-none", className)} {...props} />
}

export function AlertDescription({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("text-sm leading-relaxed opacity-95", className)} {...props} />
}
