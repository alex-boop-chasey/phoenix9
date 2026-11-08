// Body of the prs card: one row per pull request with its checks and a link to GitHub.
import { relativeTime } from "@/lib/format"
import { safeUrl } from "@/lib/safeUrl"

import type { CardBodyProps } from "../cardBodies"

interface PrRow {
  project?: string
  number?: number
  title?: string
  draft?: boolean
  checks?: string
  url?: string
  updated_at?: string
  error?: string
}

/** The pull request rows of a prs card. */
export function PrsBody({ data }: CardBodyProps) {
  const rows = (Array.isArray(data) ? data : []) as PrRow[]
  if (rows.length === 0) return <p className="muted" data-testid="prs-empty">No pull requests.</p>
  return (
    <ul className="m-0 flex list-none flex-col gap-2 p-0" data-testid="card-prs">
      {rows.map((r, i) => {
        if (r.error) return <li key={i} className="muted">{r.project}: {r.error}</li>
        const href = safeUrl(r.url)
        const label = `#${r.number} ${r.title ?? ""}`
        return (
          <li key={`${r.project}-${r.number}-${i}`} className="flex flex-wrap items-center gap-2" data-testid="pr-row">
            {href ? <a href={href} target="_blank" rel="noreferrer noopener">{label}</a> : <span>{label}</span>}
            {r.draft ? <span className="badge" data-testid="pr-draft">draft</span> : null}
            {r.checks && r.checks !== "none" ? <span className="badge" data-testid="pr-checks">{r.checks}</span> : null}
            {r.updated_at ? <span className="muted">{relativeTime(r.updated_at)}</span> : null}
          </li>
        )
      })}
    </ul>
  )
}
