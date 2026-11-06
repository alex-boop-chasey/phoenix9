// One project as a horizontal card: state edge, name and path, status, repo and the Remove, Chat and VS Code buttons.
import { memo, type MouseEvent } from "react"
import { Link, useNavigate } from "react-router"

import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import type { ProjectRow } from "@/lib/types"
import { switchState } from "@/lib/switcher"

import { runText } from "./rows"

/** The coloured state badge of a project: needs you, running, failed or idle. */
export function StateBadge({ row }: { row: ProjectRow }) {
  const state = switchState(row)
  if (state === "need") return <span className="badge b-need"><Icon name="bell-ringing" /><span className="b-t">Needs you</span></span>
  if (state === "run") {
    const text = runText(row)
    return <span className="badge b-run" title={text}><Wheel /><span className="b-t">{text}</span></span>
  }
  if (state === "fail") {
    const text = row.run ? row.run_text : row.status_line
    return <span className="badge b-bad" title={text}><Icon name="x-circle" /><span className="b-t">{text}</span></span>
  }
  return <span className="badge b-info"><Icon name="circle-dashed" /><span className="b-t">Idle</span></span>
}

function RepoPart({ row }: { row: ProjectRow }) {
  if (!row.repo) return <span className="p-repo none"><Icon name="github-logo" size="sm" /><span>No repo</span></span>
  const text = row.repo_owner ? `${row.repo_owner}/${row.repo_name}` : row.repo
  if (!row.repo_url) return <span className="p-repo none"><Icon name="github-logo" size="sm" /><span>{text}</span></span>
  return (
    <a className="p-repo" href={row.repo_url} target="_blank" rel="noreferrer"><Icon name="github-logo" size="sm" /><span>{text}</span></a>
  )
}

function ChatButton({ row, onStart }: { row: ProjectRow; onStart: () => void }) {
  const on = row.chat.state === "on"
  if (on && row.chat.url) {
    return (
      <a className="btn btn-secondary" href={row.chat.url} target="_blank" rel="noreferrer">
        <Icon name="chat-circle-text" />Chat<span className="chatdot" title="Chat on" />
      </a>
    )
  }
  if (!on) return null
  return (
    <button type="button" className="btn btn-secondary" onClick={onStart} title="Chat is on; get its link">
      <Icon name="play-circle" />Chat<span className="chatdot" title="Chat on" />
    </button>
  )
}

function CodeButton({ row }: { row: ProjectRow }) {
  if (!row.vscode_url) {
    return <button type="button" className="btn btn-secondary" disabled title={row.vscode.reason ?? "No folder to open"}><Icon name="code" />VS Code</button>
  }
  return <a className="btn btn-secondary" href={row.vscode_url} target="_blank" rel="noreferrer"><Icon name="code" />VS Code</a>
}

/** A project row; clicking anywhere except its links and buttons opens the project. Memoised: the callbacks take the project name so the parent can keep them stable. */
export const ProjectRowCard = memo(function ProjectRowCard({ row, gone, onRemove, onStartChat }: {
  row: ProjectRow
  gone: boolean
  onRemove: (name: string) => void
  onStartChat: (name: string) => void
}) {
  const navigate = useNavigate()
  const open = (e: MouseEvent) => {
    if ((e.target as HTMLElement).closest("button,a")) return
    navigate(`/p/${encodeURIComponent(row.name)}`)
  }
  return (
    <div className={`prow s-${switchState(row)}${gone ? " gone" : ""}`} data-row={row.name} onClick={open}>
      <div className="p-main">
        <Link className="p-name" to={`/p/${encodeURIComponent(row.name)}`}>{row.name}</Link>
        <span className="p-path">{row.path}</span>
      </div>
      <div className="p-meta"><span className="p-status"><StateBadge row={row} /></span><RepoPart row={row} /></div>
      <div className="p-acts">
        <button type="button" className="btn btn-ghost" onClick={() => onRemove(row.name)}><Icon name="trash" />Remove</button>
        <ChatButton row={row} onStart={() => onStartChat(row.name)} />
        <CodeButton row={row} />
      </div>
    </div>
  )
})
