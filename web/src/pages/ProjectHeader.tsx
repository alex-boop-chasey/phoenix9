// The header every project tab shares: name, state, Repo / VS Code / Chat, Start new build, details and tabs.
import { useEffect, useRef } from "react"
import { Link, NavLink, useLocation } from "react-router"

import { Icon, type IconName } from "@/components/Icon"
import { StateBadge } from "@/features/projects/ProjectRowCard"
import { startChat } from "@/features/projects/startChat"
import { formatBytes } from "@/lib/format"
import { useRefreshProjects } from "@/lib/queries"
import type { ProjectRow } from "@/lib/types"

export const TABS = ["overview", "build", "logs", "settings"] as const
const TAB_ICON: Record<(typeof TABS)[number], IconName> = {
  overview: "house-line", build: "hammer", logs: "terminal-window", settings: "gear",
}
const TAB_LABEL = { overview: "Overview", build: "Build", logs: "Logs", settings: "Settings" }

function Dock({ row }: { row: ProjectRow }) {
  const refresh = useRefreshProjects()
  const chatOn = row.chat.state === "on" && row.chat.url
  return (
    <div className="dock" role="group" aria-label="Open project">
      {row.repo_url ? (
        <a href={row.repo_url} target="_blank" rel="noreferrer"><Icon name="github-logo" size="sm" />Repo</a>
      ) : (
        <button type="button" disabled title="This project has no repo"><Icon name="github-logo" size="sm" />Repo</button>
      )}
      {row.vscode_url ? (
        <a href={row.vscode_url} target="_blank" rel="noreferrer"><Icon name="code" size="sm" />VS Code</a>
      ) : (
        <button type="button" disabled title={row.vscode.reason ?? "No folder to open"}><Icon name="code" size="sm" />VS Code</button>
      )}
      {chatOn ? (
        <a href={row.chat.url ?? undefined} target="_blank" rel="noreferrer"><Icon name="chat-circle-text" size="sm" />Chat</a>
      ) : (
        <button type="button" title="Start the chat" onClick={() => void startChat(row.name, refresh)}>
          <Icon name="play-circle" size="sm" />Start chat
        </button>
      )}
    </div>
  )
}

/** The project header with its four tabs. */
export function ProjectHeader({ row }: { row: ProjectRow }) {
  const base = `/p/${encodeURIComponent(row.name)}`
  const tabs = useRef<HTMLElement>(null)
  const { pathname } = useLocation()
  useEffect(() => {
    // Scroll the tab bar itself (never the page) so the current tab is in view.
    const bar = tabs.current, cur = bar?.querySelector<HTMLElement>('[aria-current="page"]')
    if (!bar || !cur) return
    bar.scrollLeft = Math.max(0, cur.offsetLeft - (bar.clientWidth - cur.offsetWidth) / 2)
  }, [pathname])
  return (
    <div className="phead">
      <div className="ph-row">
        <h1 className="h1">{row.name}</h1>
        <StateBadge row={row} />
        <div className="ph-r">
          <Dock row={row} />
          <Link className="btn btn-primary" to={`${base}/build?new=1`}><Icon name="hammer" />Start new build</Link>
        </div>
      </div>
      {row.description && <p className="muted">{row.description}</p>}
      <div className="ph-meta">
        <span className="mono"><Icon name="folder-simple" size="xs" /><span>{row.path}</span></span>
        <span className="mono"><Icon name="github-logo" size="xs" /><span>{row.repo || "No repo"}</span></span>
        <span>{row.size == null ? "Measuring size…" : formatBytes(row.size)}</span>
      </div>
      <nav className="tabs" ref={tabs} aria-label="Project tabs">
        {TABS.map((t) => (
          <NavLink key={t} to={`${base}/${t}`} className="tab" end>
            <Icon name={TAB_ICON[t]} />{TAB_LABEL[t]}
            {t === "overview" && row.needs_you > 0 && <span className="tc" aria-label={`${row.needs_you} waiting for you`}>{row.needs_you}</span>}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
