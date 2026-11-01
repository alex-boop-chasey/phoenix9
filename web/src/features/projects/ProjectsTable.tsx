// Desktop view: one table row per project with seven columns.
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { formatBytes } from "@/lib/format"
import type { ProjectRow } from "@/lib/types"

import { ChatLink, NameLink, RepoLink, SizeText, StatusCell, VscodeLink } from "./parts"

/** The projects as a table (Project, Path, Repo, Size, Chat, VS Code, Status). */
export function ProjectsTable({ rows }: { rows: ProjectRow[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Project</TableHead>
          <TableHead>Path</TableHead>
          <TableHead>Repo</TableHead>
          <TableHead>Size</TableHead>
          <TableHead>Chat</TableHead>
          <TableHead>VS Code</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.name}>
            <TableCell className="max-w-72 whitespace-normal align-top">
              <NameLink row={row} />
              {row.description && (
                <p className="line-clamp-2 text-sm text-muted-foreground">{row.description}</p>
              )}
            </TableCell>
            <TableCell className="max-w-48 align-top">
              <span className="block truncate font-mono text-xs text-muted-foreground" title={row.path}>
                {row.path}
              </span>
            </TableCell>
            <TableCell className="align-top">
              <RepoLink row={row} />
            </TableCell>
            <TableCell className="align-top">
              <SizeText bytes={row.size} format={formatBytes} />
            </TableCell>
            <TableCell className="align-top">
              <ChatLink row={row} />
            </TableCell>
            <TableCell className="align-top">
              <VscodeLink row={row} />
            </TableCell>
            <TableCell className="align-top">
              <StatusCell row={row} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
