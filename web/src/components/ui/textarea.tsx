import * as React from "react"
import { cn } from "@/lib/utils"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn("textarea aria-invalid:border-bad disabled:cursor-not-allowed disabled:opacity-50", className)}
      {...props}
    />
  )
}

export { Textarea }
