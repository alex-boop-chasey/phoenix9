import type { ReactNode } from "react"

import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { Badge } from "@/components/ui/badge"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import type { FailedAt, RunStatus } from "@/lib/types"

/** The result of a build in plain words, from its status and task counts; a build whose tasks all
 * passed but a run step failed says where ("Failed at: Full suite: 2 tests failed"). */
export function resultText(
  status: RunStatus,
  total: number,
  failed: number,
  currentTask?: number | null,
  failedAt?: FailedAt | null,
): string {
  switch (status) {
    case "done":
      return "Passed"
    case "failed":
      return failed > 0 ? `${failed} of ${total} tasks failed` : failedAt?.text || "Failed"
    case "stopped":
      return "Stopped"
    case "running":
      return currentTask ? `Running task ${currentTask} of ${total}` : "Running"
    case "waiting":
      return "Waiting for you"
    case "paused":
      return "Paused"
    case "paused-limit":
      return "Paused (usage limit)"
    default:
      return "Queued"
  }
}

type ResultRow = {
  status: RunStatus
  tasks_total: number
  tasks_failed: number
  current: { task?: number | null } | null
  failed_at?: FailedAt | null
}

/** The status text for a build row. */
export function rowResult(row: ResultRow): string {
  return resultText(row.status, row.tasks_total, row.tasks_failed, row.current?.task, row.failed_at)
}

/** The badge words for a result, kept short ("Failed at: Full suite"), and the whole line for its hover. */
export function badgeResult(status: RunStatus, failed: number, full: string, failedAt?: FailedAt | null) {
  if (status === "failed" && failed === 0 && failedAt) return { text: `Failed at: ${failedAt.title}`, hint: full }
  return { text: full, hint: undefined }
}

/** The badge words and hover line for a build row. */
export function rowBadge(row: ResultRow) {
  return badgeResult(row.status, row.tasks_failed, rowResult(row), row.failed_at)
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

/** The bar pieces for a build: one per task (done, failed, skipped, the running one), plus an orange piece when only the merge waits. */
export function taskPieces(status: RunStatus, total: number, passed: number, failed: number, skipped = 0): string[] {
  const pieces: string[] = []
  for (let i = 0; i < total; i++) {
    if (i < passed) pieces.push("ok")
    else if (i < passed + failed) pieces.push("bad")
    else if (i < passed + failed + skipped) pieces.push("skip")
    else if (status === "running" && i === passed + failed + skipped) pieces.push("run")
    else pieces.push("")
  }
  if (status === "waiting" && passed + skipped >= total) pieces.push("need")
  return pieces
}

/** Above this many pieces the bar becomes one thin bar split by colour. */
export const MANY_TASKS = 12

/** Pieces grouped into runs of the same colour: [colour, how many]. */
function runsOf(pieces: string[]): [string, number][] {
  const out: [string, number][] = []
  for (const c of pieces) {
    const last = out.at(-1)
    if (last && last[0] === c) last[1] += 1
    else out.push([c, 1])
  }
  return out
}

/** The hover words for a task bar, e.g. "5 passed, 1 skipped · 2 tasks needed more than one try". */
export function taskBarHint(c: { total: number; passed: number; failed?: number; skipped?: number; retried?: number }): string {
  const left = c.total - c.passed - (c.failed ?? 0) - (c.skipped ?? 0)
  const parts = [
    `${c.passed} passed`,
    c.failed ? `${c.failed} failed` : "",
    c.skipped ? `${c.skipped} skipped` : "",
    left > 0 && left < c.total ? `${left} not done yet` : "",
  ].filter(Boolean)
  const head = c.total === 0 ? "No tasks yet" : parts.join(", ")
  const r = c.retried ?? 0
  if (r === 0) return head
  return `${head} · ${r} ${r === 1 ? "task" : "tasks"} needed more than one try`
}

/** A build's task bar: one piece per task, or one thin bar split by colour when there are many tasks. */
export function TaskBar({ pieces, label, hint }: { pieces: string[]; label: string; hint?: string }) {
  const many = pieces.length > MANY_TASKS
  return (
    <div className={many ? "tbar thin" : "tbar"} aria-label={label} title={hint}>
      {many
        ? runsOf(pieces).map(([c, n], i) => <i key={i} className={c} style={{ flexGrow: n }} data-count={n} />)
        : pieces.map((c, i) => <i key={i} className={c} />)}
    </div>
  )
}

/** The colour word of a build's left edge and ring. */
export function edgeOf(status: RunStatus): "ok" | "bad" | "need" | "run" | "none" {
  if (status === "done") return "ok"
  if (status === "failed") return "bad"
  if (status === "waiting" || status === "paused") return "need"
  if (status === "running") return "run"
  return "none"
}

/** A result badge whose words are the plain result ("Passed", "1 of 3 tasks failed", "Running task 2 of 4"). */
export function ResultBadge({ status, text, hint }: { status: RunStatus; text: string; hint?: string }) {
  const edge = edgeOf(status)
  const variant = edge === "ok" ? "ok" : edge === "bad" ? "bad" : edge === "need" ? "need" : edge === "run" ? "running" : "info"
  const icon = edge === "ok" ? "check-circle" : edge === "bad" ? "x-circle" : edge === "need" ? (status === "paused" ? "pause-circle" : "bell-ringing") : status === "stopped" ? "stop-circle" : "circle-dashed"
  return (
    <Badge variant={variant} data-status={status} title={hint}>
      {edge === "run" ? <Wheel /> : <Icon name={icon} />}
      {text}
    </Badge>
  )
}
