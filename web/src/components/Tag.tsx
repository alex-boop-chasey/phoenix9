import type { ReactNode } from "react"

import { Icon, type IconName } from "@/components/Icon"
import { cn } from "@/lib/utils"

/** A small square-cornered label; tone "safety" is red, "accent" is blue. */
export function Tag({ tone, children, className }: { tone?: "safety" | "accent"; children: ReactNode; className?: string }) {
  return <span className={cn("tag", tone === "safety" && "t-safety", tone === "accent" && "t-accent", className)}>{children}</span>
}

/** A rounded pill (for example a service name), with an optional icon. */
export function Chip({ icon, children, className }: { icon?: IconName; children: ReactNode; className?: string }) {
  return (
    <span className={cn("chip", className)}>
      {icon && <Icon name={icon} size="xs" />}
      {children}
    </span>
  )
}
