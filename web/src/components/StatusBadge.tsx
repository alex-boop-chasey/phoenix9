import { Loader2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { AnyStatus } from "@/lib/types"

const LOOK: Record<AnyStatus, { label: string; className: string }> = {
  queued: { label: "Queued", className: "bg-muted text-muted-foreground" },
  pending: { label: "Pending", className: "bg-muted text-muted-foreground" },
  running: { label: "Running", className: "bg-blue-500/15 text-blue-600 dark:text-blue-400" },
  waiting: { label: "Waiting for you", className: "bg-amber-500/15 text-amber-700 dark:text-amber-400" },
  "paused-limit": { label: "Paused (usage limit)", className: "bg-orange-500/15 text-orange-700 dark:text-orange-400" },
  done: { label: "Done", className: "bg-green-500/15 text-green-700 dark:text-green-400" },
  passed: { label: "Passed", className: "bg-green-500/15 text-green-700 dark:text-green-400" },
  failed: { label: "Failed", className: "bg-red-500/15 text-red-700 dark:text-red-400" },
  stopped: { label: "Stopped", className: "bg-muted text-muted-foreground" },
  skipped: { label: "Skipped", className: "bg-muted text-muted-foreground" },
}

/** A coloured badge for a run, task or step status. */
export function StatusBadge({ status, className }: { status: AnyStatus; className?: string }) {
  const look = LOOK[status] ?? { label: status, className: "bg-muted text-muted-foreground" }
  return (
    <Badge variant="secondary" className={cn(look.className, className)} data-status={status}>
      {status === "running" && <Loader2 className="animate-spin" data-testid="spinner" aria-hidden />}
      {look.label}
    </Badge>
  )
}
