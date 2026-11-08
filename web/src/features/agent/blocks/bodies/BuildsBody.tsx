// Body of the builds card: a compact list of builds, each opening its run.
import { Link } from "react-router"

import { RelativeTime } from "@/components/RelativeTime"
import { ResultBadge, rowResult } from "@/features/build/parts"
import type { BuildRow } from "@/lib/types"

import type { CardBodyProps } from "../cardBodies"

function runUrl(name: string, id: string) {
  return `/p/${encodeURIComponent(name)}/build?run=${encodeURIComponent(id)}`
}

/** The compact build list of a builds card. */
export function BuildsBody({ data }: CardBodyProps) {
  const rows = (Array.isArray(data) ? data : []) as BuildRow[]
  if (rows.length === 0) return <p className="muted" data-testid="builds-empty">No builds yet.</p>
  return (
    <ul className="flex flex-col gap-2" data-testid="card-builds">
      {rows.map((row) => (
        <li key={row.run_id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1" data-run={row.run_id}>
          <Link className="mono min-w-0 truncate" to={runUrl(row.project, row.run_id)}>{row.run_id}</Link>
          <span className="flex items-center gap-2">
            <ResultBadge status={row.status} text={rowResult(row)} />
            <small className="muted"><RelativeTime iso={row.started || row.created} /></small>
          </span>
        </li>
      ))}
    </ul>
  )
}
