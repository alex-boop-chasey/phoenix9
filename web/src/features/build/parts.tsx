import type { ReactNode } from "react"

import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import type { RunStatus } from "@/lib/types"

/** The result of a build in plain words, from its status and task counts. */
export function resultText(
  status: RunStatus,
  total: number,
  failed: number,
  currentTask?: number | null,
): string {
  switch (status) {
    case "done":
      return "Passed"
    case "failed":
      return failed > 0 ? `${failed} of ${total} tasks failed` : "Failed"
    case "stopped":
      return "Stopped"
    case "running":
      return currentTask ? `Running task ${currentTask} of ${total}` : "Running"
    case "waiting":
      return "Waiting for you"
    case "paused-limit":
      return "Paused (usage limit)"
    default:
      return "Queued"
  }
}

/** The status text for a build row. */
export function rowResult(row: {
  status: RunStatus
  tasks_total: number
  tasks_failed: number
  current: { task?: number | null } | null
}): string {
  return resultText(row.status, row.tasks_total, row.tasks_failed, row.current?.task)
}

/** One line of text, cut short when long, with the whole text in a tooltip. */
export function ShortText({ text, max = 90, className }: { text: string; max?: number; className?: string }) {
  if (text.length <= max) return <span className={className}>{text}</span>
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className={className} tabIndex={0}>{text.slice(0, max).trimEnd()}…</span>
        </TooltipTrigger>
        <TooltipContent className="max-w-sm">{text}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

/** A muted note under a heading. */
export function Muted({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>
}

/** The bar pieces for a build: one per task (done, failed, the running one), plus an orange piece when only the merge waits. */
export function taskPieces(status: RunStatus, total: number, passed: number, failed: number): string[] {
  const pieces: string[] = []
  for (let i = 0; i < total; i++) {
    if (i < passed) pieces.push("ok")
    else if (i < passed + failed) pieces.push("bad")
    else if (status === "running" && i === passed + failed) pieces.push("run")
    else pieces.push("")
  }
  if (status === "waiting" && passed >= total) pieces.push("need")
  return pieces
}

/** The colour word of a build's left edge and ring. */
export function edgeOf(status: RunStatus): "ok" | "bad" | "need" | "run" | "none" {
  if (status === "done") return "ok"
  if (status === "failed") return "bad"
  if (status === "waiting") return "need"
  if (status === "running") return "run"
  return "none"
}

/** A result badge whose words are the plain result ("Passed", "1 of 3 tasks failed", "Running task 2 of 4"). */
export function ResultBadge({ status, text }: { status: RunStatus; text: string }) {
  const edge = edgeOf(status)
  const variant = edge === "ok" ? "ok" : edge === "bad" ? "bad" : edge === "need" ? "need" : edge === "run" ? "running" : "info"
  const icon = edge === "ok" ? "check-circle" : edge === "bad" ? "x-circle" : edge === "need" ? "bell-ringing" : status === "stopped" ? "stop-circle" : "circle-dashed"
  return (
    <Badge variant={variant} data-status={status}>
      {edge === "run" ? <Wheel /> : <Icon name={icon} />}
      {text}
    </Badge>
  )
}
