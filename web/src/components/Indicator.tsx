import { Icon } from "@/components/Icon"
import { cn } from "@/lib/utils"

export type IndicatorKind = "passed" | "failed" | "pending" | "running" | "needs-you" | "off"

const KIND: Record<IndicatorKind, { cls: string; label: string }> = {
  passed: { cls: "ind-ok", label: "Passed" },
  failed: { cls: "ind-bad", label: "Failed" },
  pending: { cls: "ind-pend", label: "Pending" },
  running: { cls: "ind-run", label: "Running" },
  "needs-you": { cls: "ind-need", label: "Needs you" },
  off: { cls: "ind-off", label: "Off" },
}

/** The round status dot: passed, failed, pending (dashed), running (spinner), needs you, or off. */
export function Indicator({ kind, small, className }: { kind: IndicatorKind; small?: boolean; className?: string }) {
  const look = KIND[kind]
  return (
    <span className={cn("ind", look.cls, small && "sm", className)} data-indicator={kind} role="img" aria-label={look.label}>
      {kind === "passed" && <Icon name="check" size="xs" />}
      {kind === "failed" && <Icon name="x" size="xs" />}
      {kind === "needs-you" && <Icon name="bell-ringing" size="xs" />}
    </span>
  )
}

/** The small spinning wheel used inside buttons and badges. */
export function Wheel({ className }: { className?: string }) {
  return <span className={cn("wheel", className)} data-testid="spinner" aria-hidden />
}
