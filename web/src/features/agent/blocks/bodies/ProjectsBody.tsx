// Body of the projects card: the Projects page's tiles, one per project, with a pull-request line when one waits.
import { ProjectTile } from "@/features/projects/ProjectTile"
import type { ProjectQueryResult, ProjectRow } from "@/lib/types"

import type { CardBodyProps } from "../cardBodies"

type CardRow = ProjectRow & { needs_merge?: boolean; pr?: { number: number; title: string; url: string } | null }

/** The project tiles of a projects card. */
export function ProjectsBody({ data }: CardBodyProps) {
  const found = data as Partial<ProjectQueryResult> | null
  const rows = [...(found?.top ?? []), ...(found?.rest ?? [])] as CardRow[]
  if (rows.length === 0) return <p className="muted" data-testid="projects-empty">No projects match.</p>
  return (
    <div className="plist" data-testid="card-projects">
      {rows.map((row) => (
        <ProjectTile key={row.name} row={row} pr={row.needs_merge && row.pr ? row.pr : null} />
      ))}
    </div>
  )
}
