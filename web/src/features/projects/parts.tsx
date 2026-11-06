// Small pieces shared by the projects table and the phone cards.
import { Link } from "react-router"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import type { ProjectRow } from "@/lib/types"

import { runText } from "./rows"

const linkClass = "text-primary underline-offset-4 hover:underline"

/** The repo as an external link, muted text for a non-GitHub repo, or a dash. */
export function RepoLink({ row }: { row: ProjectRow }) {
  if (!row.repo) return <span className="text-muted-foreground">—</span>
  if (!row.repo_owner || !row.repo_url) return <span className="text-muted-foreground">{row.repo}</span>
  return (
    <a href={row.repo_url} target="_blank" rel="noreferrer" className={linkClass}>
      {row.repo_owner}/{row.repo_name}
    </a>
  )
}

/** "Open chat" link, or a dash when there is no chat. */
export function ChatLink({ row }: { row: ProjectRow }) {
  if (row.chat.kind === "none" || !row.chat.url) return <span className="text-muted-foreground">—</span>
  return (
    <a href={row.chat.url} target="_blank" rel="noreferrer" className={linkClass}>
      Open chat
      {row.chat.kind === "environment" && <span className="ml-1 text-xs text-muted-foreground">(project)</span>}
    </a>
  )
}

/** The "Open" link to VS Code in a new tab. */
export function VscodeLink({ row, label = "Open" }: { row: ProjectRow; label?: string }) {
  if (!row.vscode_url) return <span className="text-muted-foreground" title={row.vscode?.reason ?? undefined}>—</span>
  return (
    <a href={row.vscode_url} target="_blank" rel="noreferrer" className={linkClass}>
      {label}
    </a>
  )
}

/** The amber "Needs you" badge, linking to the project's overview. */
export function NeedsYouBadge({ row }: { row: ProjectRow }) {
  return (
    <Link to={`/p/${encodeURIComponent(row.name)}/overview`} aria-label={`${row.name} needs you`}>
      <Badge variant="secondary" className="bg-amber-500/15 text-amber-700 dark:text-amber-400">
        Needs you
      </Badge>
    </Link>
  )
}

/** Chat service dot plus the harness state (or the Needs you badge). */
export function StatusCell({ row, className }: { row: ProjectRow; className?: string }) {
  const on = row.state === "on"
  return (
    <div className={cn("flex flex-col items-start gap-1 text-sm", className)}>
      <span className="inline-flex items-center gap-1.5">
        <span
          aria-hidden
          className={cn("size-2 rounded-full", on ? "bg-green-500" : "bg-muted-foreground/50")}
        />
        {on ? "Chat on" : "Chat off"}
      </span>
      {row.needs_you > 0 ? <NeedsYouBadge row={row} /> : <span className="text-muted-foreground">{runText(row)}</span>}
    </div>
  )
}

/** The project name as a bold link to its page. */
export function NameLink({ row }: { row: ProjectRow }) {
  return (
    <Link to={`/p/${encodeURIComponent(row.name)}`} className="font-semibold hover:underline">
      {row.name}
    </Link>
  )
}

/** The size, or a muted "…" while it is being measured. */
export function SizeText({ bytes, format }: { bytes: number | null; format: (n: number | null) => string }) {
  if (bytes == null) {
    return (
      <span className="text-muted-foreground" title="Being measured">
        …
      </span>
    )
  }
  return <>{format(bytes)}</>
}
