import type { ReactNode } from "react"

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
