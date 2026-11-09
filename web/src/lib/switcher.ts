// How a project shows in the switcher. The state and its words come from the backend (phoenix9/status.py);
// this file only orders them.
import type { Activity, ProjectRow } from "@/lib/types"

export type SwitchState = Activity

const ORDER: Record<SwitchState, number> = { need: 0, run: 1, fail: 2, idle: 3 }

/** The state of a project: needs you, running, failed or idle (the backend's `activity`). */
export function switchState(p: ProjectRow): SwitchState {
  return p.activity ?? "idle"
}

/** One plain line about a project for the switcher (the backend's `status_line`). */
export function switchLine(p: ProjectRow): string {
  return p.status_line ?? ""
}

/** Projects sorted needs-you, running, failed, idle, then by name. */
export function sortForSwitcher(rows: ProjectRow[]): ProjectRow[] {
  return [...rows].sort((a, b) => ORDER[switchState(a)] - ORDER[switchState(b)] || a.name.localeCompare(b.name))
}

export type SwitchGroupKey = "agent" | "building" | "paused" | "rest"
export interface SwitchGroup { key: SwitchGroupKey; title: string; rows: ProjectRow[] }

const GROUPS: { key: SwitchGroupKey; title: string }[] = [
  { key: "agent", title: "Agent working" }, { key: "building", title: "Building" },
  { key: "paused", title: "Paused / needs you" }, { key: "rest", title: "Projects" },
]

/** The first group a project belongs to: agent work, a build going, paused or needing Alex, or the rest. */
export function groupOf(p: ProjectRow): SwitchGroupKey {
  if (p.edit || p.plan) return "agent"
  const status = p.run?.status
  if (status === "running" || status === "queued") return "building"
  if (status === "waiting" || status === "paused" || status === "paused-limit" || p.needs_you > 0 || switchState(p) === "need") return "paused"
  return "rest"
}

/** True when the agent's work on the project has stalled (an edit with no activity, nothing else going on). */
export function agentStalled(p: ProjectRow): boolean {
  return p.edit?.status === "stalled" && !p.plan
}

/** The title of the edit or plan the agent is on (empty when none). */
export function agentTitle(p: ProjectRow): string {
  return p.plan?.title || p.edit?.title || ""
}

/** The rows in the four groups (a project once, in the first that fits; empty groups left out). */
export function groupForSwitcher(rows: ProjectRow[]): SwitchGroup[] {
  const sorted = sortForSwitcher(rows)
  return GROUPS.map((g) => ({ ...g, rows: sorted.filter((p) => groupOf(p) === g.key) })).filter((g) => g.rows.length > 0)
}
