import * as React from "react"

import { cn } from "@/lib/utils"

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

const Input = React.forwardRef<HTMLInputElement, InputProps>(({ className, type, ...props }, ref) => {
  return (
    <input
      ref={ref}
      type={type}
      className={cn(
        "flex h-10 w-full rounded-xl border border-input/80 bg-background/80 px-3 py-2 text-sm text-foreground shadow-sm backdrop-blur-sm transition file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground focus-visible:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
})
Input.displayName = "Input"

export { Input }
