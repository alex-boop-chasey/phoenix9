import { Hammer } from "lucide-react"
import { Link, useNavigate } from "react-router"

import { EmptyState } from "@/components/EmptyState"
import { RelativeTime } from "@/components/RelativeTime"
import { StatusBadge } from "@/components/StatusBadge"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useIsDesktop } from "@/features/projects/useIsDesktop"
import type { BuildRow } from "@/lib/types"

import { rowResult } from "./parts"

/** Newest first, by start time (queued builds by creation time). */
export function newestFirst(rows: BuildRow[]): BuildRow[] {
  const when = (r: BuildRow) => r.started || r.created || ""
  return [...rows].sort((a, b) => when(b).localeCompare(when(a)))
}

function runUrl(name: string, id: string) {
  return `/p/${encodeURIComponent(name)}/build?run=${encodeURIComponent(id)}`
}

function ResultCell({ row }: { row: BuildRow }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <StatusBadge status={row.status} />
      <span className="text-sm">{rowResult(row)}</span>
    </span>
  )
}

/** The previous builds of a project: a table on desktop, cards on a phone. */
export function BuildList({ name, rows }: { name: string; rows: BuildRow[] }) {
  const desktop = useIsDesktop()
  const navigate = useNavigate()
  if (rows.length === 0) {
    return <EmptyState icon={Hammer} title="No builds yet" line="A build runs a spec as a series of small steps." />
  }
  const sorted = newestFirst(rows)
  if (!desktop) {
    return (
      <ul className="flex flex-col gap-3">
        {sorted.map((row) => (
          <li key={row.run_id}>
            <Card className="cursor-pointer py-3" onClick={() => navigate(runUrl(name, row.run_id))}>
              <CardContent className="flex flex-col gap-2 px-4">
                <Link to={runUrl(name, row.run_id)} className="font-medium text-primary hover:underline">
                  {row.title || row.run_id}
                </Link>
                <ResultCell row={row} />
                <p className="flex flex-wrap gap-x-3 text-xs text-muted-foreground">
                  <RelativeTime iso={row.started || row.created} />
                  <span>{row.preset}</span>
                  <span>{row.duration || "-"}</span>
                  <span>{row.cost || "-"}</span>
                </p>
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>
    )
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Date</TableHead>
          <TableHead>Spec</TableHead>
          <TableHead>Preset</TableHead>
          <TableHead>Result</TableHead>
          <TableHead>Duration</TableHead>
          <TableHead>Cost</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {sorted.map((row) => (
          <TableRow key={row.run_id} className="cursor-pointer" onClick={() => navigate(runUrl(name, row.run_id))}>
            <TableCell><RelativeTime iso={row.started || row.created} /></TableCell>
            <TableCell>
              <Link to={runUrl(name, row.run_id)} className="text-primary hover:underline">
                {row.title || row.run_id}
              </Link>
            </TableCell>
            <TableCell>{row.preset}</TableCell>
            <TableCell><ResultCell row={row} /></TableCell>
            <TableCell>{row.duration || "-"}</TableCell>
            <TableCell>{row.cost || "-"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
