import * as React from "react"
import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn("input aria-invalid:border-bad disabled:cursor-not-allowed disabled:opacity-50", className)}
      {...props}
    />
  )
}

export { Input }
