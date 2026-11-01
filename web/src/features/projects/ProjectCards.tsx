// Phone view: one card per project, no table and no sideways scrolling.
import { Card, CardContent } from "@/components/ui/card"
import { formatBytes } from "@/lib/format"
import type { ProjectRow } from "@/lib/types"

import { ChatLink, NameLink, RepoLink, SizeText, StatusCell, VscodeLink } from "./parts"

/** The projects as a list of cards. */
export function ProjectCards({ rows }: { rows: ProjectRow[] }) {
  return (
    <ul className="flex flex-col gap-3">
      {rows.map((row) => (
        <li key={row.name}>
          <Card className="py-3">
            <CardContent className="flex flex-col gap-2 px-4">
              <div className="min-w-0">
                <NameLink row={row} />
                {row.description && (
                  <p className="line-clamp-2 text-sm text-muted-foreground">{row.description}</p>
                )}
              </div>
              <StatusCell row={row} />
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
                <span className="inline-flex gap-1">
                  Repo: <RepoLink row={row} />
                </span>
                <ChatLink row={row} />
                <VscodeLink row={row} label="VS Code" />
              </div>
              <p className="flex flex-wrap gap-x-3 text-xs text-muted-foreground">
                <span className="break-all font-mono">{row.path}</span>
                <span>
                  <SizeText bytes={row.size} format={formatBytes} />
                </span>
              </p>
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  )
}
