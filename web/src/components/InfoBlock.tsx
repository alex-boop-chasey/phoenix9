import type { ReactNode } from "react"

import { Icon, type IconName } from "@/components/Icon"
import { cn } from "@/lib/utils"

const ICON: Record<"info" | "ok" | "bad" | "tip", IconName> = {
  info: "info",
  ok: "check-circle",
  bad: "warning-octagon",
  tip: "lightbulb",
}

/** A coloured note block: plain info, ok (green), bad (red) or tip (blue). */
export function InfoBlock({ tone = "info", children, className }: {
  tone?: "info" | "ok" | "bad" | "tip"
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn("blk-info", tone !== "info" && tone, className)} data-tone={tone}>
      <Icon name={ICON[tone]} />
      <div className="min-w-0">{children}</div>
    </div>
  )
}
