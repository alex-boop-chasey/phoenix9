// The builds ledger: one row per build with a coloured left edge, a task bar and a result badge.
import { Hammer } from "lucide-react"
import { Link, useNavigate } from "react-router"

import { EmptyState } from "@/components/EmptyState"
import { RelativeTime } from "@/components/RelativeTime"
import { Tag } from "@/components/Tag"
import type { BuildRow } from "@/lib/types"

import { edgeOf, ResultBadge, rowResult, TaskBar, taskBarHint, taskPieces } from "./parts"

/** Newest first, by start time (queued builds by creation time). */
export function newestFirst(rows: BuildRow[]): BuildRow[] {
  const when = (r: BuildRow) => r.started || r.created || ""
  return [...rows].sort((a, b) => when(b).localeCompare(when(a)))
}

function runUrl(name: string, id: string) {
  return `/p/${encodeURIComponent(name)}/build?run=${encodeURIComponent(id)}`
}

const SPINE: Record<string, string> = {
  ok: "var(--ok)", bad: "var(--bad)", need: "var(--attn)", run: "var(--accent)", none: "var(--line-strong)",
}

/** The previous and current builds of a project as a ledger; the selected one is highlighted. */
export function BuildList({ name, rows, selected }: { name: string; rows: BuildRow[]; selected?: string }) {
  const navigate = useNavigate()
  if (rows.length === 0) {
    return <EmptyState icon={Hammer} title="No builds yet" line="A build runs a spec as a series of small steps." />
  }
  return (
    <div className="tscroll">
      <table className="ledger">
        <thead>
          <tr>
            <th>Build</th><th>Preset</th><th>Tasks</th><th>Result</th><th>Duration</th><th>Cost</th>
          </tr>
        </thead>
        <tbody>
          {newestFirst(rows).map((row) => {
            const skipped = row.tasks_skipped ?? 0
            const pieces = taskPieces(row.status, row.tasks_total, row.tasks_passed, row.tasks_failed, skipped)
            const hint = taskBarHint({
              total: row.tasks_total, passed: row.tasks_passed, failed: row.tasks_failed, skipped, retried: row.tasks_retried,
            })
            return (
              <tr
                key={row.run_id} className={row.run_id === selected ? "sel" : undefined}
                aria-selected={row.run_id === selected} data-run={row.run_id}
                style={{ ["--spine" as string]: SPINE[edgeOf(row.status)] }}
                onClick={() => navigate(runUrl(name, row.run_id))}
              >
                <td>
                  <b><Link to={runUrl(name, row.run_id)}>{row.title || row.run_id}</Link></b>
                  <small><RelativeTime iso={row.started || row.created} />{row.discarded && " · work discarded"}</small>
                </td>
                <td><Tag>{row.preset}</Tag></td>
                <td className="tcell" title={hint}>
                  <TaskBar pieces={pieces} label={`${row.tasks_passed} of ${row.tasks_total} tasks done`} hint={hint} />
                </td>
                <td><ResultBadge status={row.status} text={rowResult(row)} /></td>
                <td className="mono">{row.duration || "-"}</td>
                <td className="mono">{row.cost || "-"}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
