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
