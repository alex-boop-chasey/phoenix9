// How far the running build's current step (and the whole build) has come, from past builds' step times.
import { formatDuration } from "@/lib/format"
import type { RunDetail, RunEstimates, StepGroup, StepLine } from "@/lib/types"

const LIVE = ["running", "waiting"]
const TASK_ENDED = ["passed", "failed", "skipped"]

/** The line of the step the build is on now (running or waiting), if any. */
export function currentLine(run: RunDetail): StepLine | undefined {
  const live = run.steps.filter((l) => LIVE.includes(l.status))
  const step = run.current?.step
  const task = run.current?.task ?? null
  const mine = live.filter((l) => l.step === step && (l.task ?? null) === task)
  const pick = (ls: StepLine[]) =>
    ls.reduce<StepLine | undefined>((best, l) => (!best || (l.started || "") >= (best.started || "") ? l : best), undefined)
  return pick(mine) ?? pick(live)
}

/** Seconds since an ISO time (0 when it is missing or unreadable). */
function since(iso: string | undefined, now: number): number {
  const t = iso ? Date.parse(iso) : NaN
  return Number.isFinite(t) ? Math.max(0, (now - t) / 1000) : 0
}

/** How full the ring is for elapsed ÷ estimate: true to time up to 80%, then slowing, never past 95%. */
export function ringFill(ratio: number): number {
  if (!(ratio > 0)) return 0
  if (ratio <= 0.8) return ratio
  return Math.min(0.949, 0.95 - 0.15 * Math.exp(-(ratio - 0.8) / 0.15))
}

/** "about 3 min to go" (never under a minute); "about 1 h 20 min to go" for long waits. */
export function toGo(seconds: number): string {
  const mins = Math.max(1, Math.ceil(seconds / 60))
  return `about ${mins < 60 ? `${mins} min` : formatDuration(mins * 60)} to go`
}

export interface StepProgress {
  /** 0..0.95 ring fill, or null for the calm moving ring (no history for this step). */
  fill: number | null
  /** The line beside the ring ("about 3 min to go", "taking longer than usual"), or "" without history. */
  line: string
}

/** Progress of the step the build is on now. */
export function stepProgress(run: RunDetail, est: RunEstimates | undefined, now: number): StepProgress {
  const line = currentLine(run)
  const typical = line ? est?.steps[line.step]?.seconds : undefined
  if (!line || line.status !== "running" || !typical || typical <= 0) return { fill: null, line: "" }
  const elapsed = since(line.started, now)
  const ratio = elapsed / typical
  return { fill: ringFill(ratio), line: ratio >= 1 ? "taking longer than usual" : toGo(typical - elapsed) }
}

/** Names of the switched-on steps of a group. */
function onSteps(run: RunDetail, group: StepGroup): string[] {
  const off = new Set((run.plan.steps ?? []).filter((r) => !r.on).map((r) => r.name))
  return (run.plan.groups?.[group] ?? []).filter((n) => !off.has(n))
}

/** Seconds a run-level step still needs: 0 once it ended, the rest of its estimate while it runs. */
function runStepLeft(run: RunDetail, est: RunEstimates, name: string, now: number): number {
  const typical = est.steps[name]?.seconds ?? 0
  const lines = run.steps.filter((l) => l.step === name && l.task == null)
  if (!lines.length) return typical
  const live = lines.find((l) => LIVE.includes(l.status))
  return live ? Math.max(0, typical - since(live.started, now)) : 0
}

/** Seconds the whole build still needs once the tasks are known (tasks left × typical task time), or null. */
export function buildLeft(run: RunDetail, est: RunEstimates | undefined, now: number): number | null {
  const tasks = Object.entries(run.tasks)
  const perTask = est?.task?.seconds
  if (!est || !tasks.length || !perTask) return null
  let left = 0
  const current = run.current?.task ?? null
  for (const [n, t] of tasks) {
    if (TASK_ENDED.includes(t.status)) continue
    const lines = run.steps.filter((l) => l.task === Number(n) && l.started)
    if (Number(n) !== current || !lines.length) {
      left += perTask
      continue
    }
    const first = lines.map((l) => l.started).sort()[0]
    left += Math.max(0, perTask - since(first, now))
  }
  for (const name of [...onSteps(run, "run-start"), ...onSteps(run, "run-finish")]) left += runStepLeft(run, est, name, now)
  return left
}
