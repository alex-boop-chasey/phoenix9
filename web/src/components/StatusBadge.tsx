import { Icon, type IconName } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { Badge } from "@/components/ui/badge"
import type { AnyStatus } from "@/lib/types"

type Variant = "ok" | "bad" | "running" | "info" | "need"
const LOOK: Record<AnyStatus, { label: string; variant: Variant; icon?: IconName }> = {
  queued: { label: "Queued", variant: "info", icon: "circle-dashed" },
  pending: { label: "Pending", variant: "info", icon: "circle-dashed" },
  running: { label: "Running", variant: "running" },
  waiting: { label: "Waiting for you", variant: "need", icon: "bell-ringing" },
  "paused-limit": { label: "Paused (usage limit)", variant: "info", icon: "hand-palm" },
  done: { label: "Done", variant: "ok", icon: "check-circle" },
  passed: { label: "Passed", variant: "ok", icon: "check-circle" },
  failed: { label: "Failed", variant: "bad", icon: "x-circle" },
  stopped: { label: "Stopped", variant: "info", icon: "stop-circle" },
  skipped: { label: "Skipped", variant: "info", icon: "circle-dashed" },
}

/** A coloured badge for a run, task or step status (orange only for "waiting for you"). */
export function StatusBadge({ status, className }: { status: AnyStatus; className?: string }) {
  const look = LOOK[status] ?? { label: status, variant: "info" as Variant }
  return (
    <Badge variant={look.variant} className={className} data-status={status}>
      {status === "running" ? <Wheel /> : look.icon && <Icon name={look.icon} />}
      {look.label}
    </Badge>
  )
}
