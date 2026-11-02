// How a project shows in the switcher: its state, one-line words, and the sort order.
import type { ProjectRow } from "@/lib/types"

export type SwitchState = "need" | "run" | "fail" | "idle"

const ORDER: Record<SwitchState, number> = { need: 0, run: 1, fail: 2, idle: 3 }

/** The state of a project: needs you, running, failed or idle. */
export function switchState(p: ProjectRow): SwitchState {
  if (p.needs_you > 0 || p.run?.status === "waiting") return "need"
  if (p.run?.status === "failed" || p.run?.status === "paused-limit") return "fail"
  if (p.run && (p.run.status === "running" || p.run.status === "queued")) return "run"
  return "idle"
}

/** One plain line about a project for the switcher. */
export function switchLine(p: ProjectRow): string {
  const s = switchState(p)
  if (s === "need") return p.needs_you > 1 ? `${p.needs_you} questions waiting` : "1 question waiting"
  if (s === "fail") return p.run?.status === "paused-limit" ? "Paused at a limit" : "Last build failed"
  if (s === "run") return p.run?.task ? `Building, task ${p.run.task} of ${p.run.tasks}` : "Build queued"
  return p.last_used ? `Idle, used ${p.last_used}` : "Idle"
}

/** Projects sorted needs-you, running, failed, idle, then by name. */
export function sortForSwitcher(rows: ProjectRow[]): ProjectRow[] {
  return [...rows].sort((a, b) => ORDER[switchState(a)] - ORDER[switchState(b)] || a.name.localeCompare(b.name))
}
