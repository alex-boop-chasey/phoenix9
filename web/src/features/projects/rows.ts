// Sorting and filtering of project rows, and the plain words for a row's status.
import type { ProjectRow } from "@/lib/types"

export const NO_REPO = "__none__"
export const ALL_OWNERS = "__all__"

/** Needs-you first, then running, then by name. */
export function sortRows(rows: ProjectRow[]): ProjectRow[] {
  const rank = (r: ProjectRow) => (r.needs_you > 0 ? 0 : r.run?.status === "running" ? 1 : 2)
  return [...rows].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name))
}

/** The distinct repo owners present in the rows, sorted. */
export function ownersOf(rows: ProjectRow[]): string[] {
  return [...new Set(rows.map((r) => r.repo_owner).filter(Boolean))].sort()
}

/** Keep rows matching the search text (name or description) and the owner choice. */
export function filterRows(rows: ProjectRow[], q: string, owner: string): ProjectRow[] {
  const needle = q.trim().toLowerCase()
  return rows.filter((r) => {
    if (needle && !`${r.name} ${r.description}`.toLowerCase().includes(needle)) return false
    if (owner === ALL_OWNERS || owner === "") return true
    if (owner === NO_REPO) return r.repo === ""
    return r.repo_owner === owner
  })
}

/** The harness state in words, taken from the structured run (never the harness string). */
export function runText(row: ProjectRow): string {
  const run = row.run
  if (!run) return "Idle"
  switch (run.status) {
    case "queued":
      return "Queued"
    case "running":
      return run.task != null ? `Running task ${run.task} of ${run.tasks}` : "Running"
    case "waiting":
      return "Waiting for you"
    case "paused-limit":
      return "Paused (usage limit)"
    default:
      return "Idle"
  }
}
