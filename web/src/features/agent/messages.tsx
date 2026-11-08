// Message components of the Phoenix agent panel: bubbles, agent text, dividers, notices, working dots, the list.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"

import { ActionCard, ActionGroup } from "@/features/agent/ActionCard"
import { BlockView } from "@/features/agent/blocks/BlockView"
import { parseBlocks } from "@/features/agent/blocks/parse"
import { Markdown } from "@/features/agent/markdown"
import type { ActionItem, AgentItem, AgentState, NoticeItem, UserItem } from "@/features/agent/useAgent"

function clock(at: string): string {
  const d = new Date(at)
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false })
}

function dayKey(at: string): string {
  const d = new Date(at)
  return Number.isNaN(d.getTime()) ? "" : `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

/** The tag shown on a user bubble: "app", "from <name>", or none. */
export function originTag(origin: string): string | null {
  if (origin === "app") return "app"
  if (origin.startsWith("peer:")) return `from ${origin.slice(5)}`
  return null
}

/** Alex's message: right-aligned bubble with an origin tag and an optional "queued" pill. */
export function UserBubble({ item, queued = false }: { item: UserItem; queued?: boolean }) {
  const tag = originTag(item.origin)
  return (
    <div className="ag-row ag-user" data-testid="agent-user">
      <div className="ag-bubble">
        {(tag || queued) && (
          <div className="ag-meta">
            {tag && <span className="ag-tag">{tag}</span>}
            {queued && <span className="pill">queued</span>}
          </div>
        )}
        <div className="ag-text">{item.text}</div>
      </div>
    </div>
  )
}

/** The agent's reply: left-aligned, no bubble, markdown as elements and reply blocks (frozen ones have no buttons). */
export function AgentMessage({ markdown, frozen = false, at, later }: { markdown: string; frozen?: boolean; at?: string; later?: string[] }) {
  const parts = useMemo(() => parseBlocks(markdown), [markdown])
  return (
    <div className="ag-row ag-agent" data-testid="agent-message">
      {parts.map((p, n) => p.type === "text"
        ? <Markdown key={n} text={p.text} />
        : <BlockView key={n} part={p} frozen={frozen} at={at} later={later} />)}
    </div>
  )
}

/** A divider line: "New conversation · 14:02" or a date. */
export function Divider({ label }: { label: string }) {
  return <div className="ag-divider" role="separator" aria-label={label}><span>{label}</span></div>
}

/** A grey one-line row. */
export function Notice({ item }: { item: NoticeItem }) {
  return <div className="ag-notice" data-testid="agent-notice">{item.text}</div>
}

/** Three dots plus the title of the running action; the dots stay still under reduced motion. */
export function WorkingIndicator({ title }: { title?: string }) {
  return (
    <div className="ag-working" role="status" aria-label="Phoenix agent is working" data-testid="agent-working">
      <span className="ag-dots" aria-hidden="true"><i /><i /><i /></span>
      {title && <span className="ag-working-title">{title}</span>}
    </div>
  )
}

/** The running action's title, if any. */
function runningTitle(items: AgentItem[]): string | undefined {
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i]
    if (it?.type === "action" && it.status === "running") return it.title
  }
  return undefined
}

/** Texts of queued items that are pending and have no matching later user item. */
function pendingQueued(items: AgentItem[]): Set<number> {
  const out = new Set<number>()
  items.forEach((it, idx) => {
    if (it.type !== "queued" || !it.pending) return
    const answered = items.slice(idx + 1).some((o) => o.type === "user" && o.text === it.text)
    if (!answered) out.add(idx)
  })
  return out
}

/** Texts of the user items after position idx. */
function laterUsers(items: AgentItem[], idx: number): string[] {
  return items.slice(idx + 1).flatMap((o) => (o.type === "user" ? [o.text] : []))
}

function sessionLabel(next: AgentItem | undefined): string {
  const at = next && "at" in next ? clock(next.at) : ""
  return at ? `New conversation · ${at}` : "New conversation"
}

function dateLabel(at: string): string {
  return new Date(at).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", year: "numeric" })
}

/** The scrolling list of messages, with the working indicator, empty state and "New messages" button. */
export function MessageList({ items, state }: { items: AgentItem[]; state?: AgentState }) {
  const box = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  const [away, setAway] = useState(false)
  const pending = useMemo(() => pendingQueued(items), [items])
  const shown = items.filter((i) => i.type !== "thinking")
  const working = state === "working"

  const jump = () => {
    const el = box.current
    if (el) el.scrollTop = el.scrollHeight
    pinned.current = true
    setAway(false)
  }

  useLayoutEffect(() => {
    if (pinned.current) {
      const el = box.current
      if (el) el.scrollTop = el.scrollHeight
    }
  }, [items, working])

  useEffect(() => {
    if (!pinned.current && items.length) setAway(true)
  }, [items])

  const onScroll = () => {
    const el = box.current
    if (!el) return
    const atEnd = el.scrollHeight - el.scrollTop - el.clientHeight < 24
    pinned.current = atEnd
    if (atEnd) setAway(false)
  }

  if (!shown.length && !working) {
    return <p className="ag-empty">Ask about your projects, builds or what needs you.</p>
  }

  const rows: React.ReactNode[] = []
  let day = ""
  const lastDivider = items.reduce((acc, it, n) => (it.type === "session" ? n : acc), -1)
  for (let idx = 0; idx < items.length; idx++) {
    const it = items[idx] as AgentItem
    const key = `${it.type}-${it.line}-${idx}`
    if (it.type === "thinking") continue
    if (it.type === "action") {
      const run: ActionItem[] = [it]
      while (items[idx + 1]?.type === "action" || items[idx + 1]?.type === "thinking") {
        const nx = items[idx + 1] as AgentItem
        if (nx.type === "action") run.push(nx)
        idx++
      }
      rows.push(run.length >= 3 ? <ActionGroup key={key} items={run} /> : run.map((a, n) => <ActionCard key={`${key}-${n}`} item={a} />))
      continue
    }
    if ("at" in it) {
      const k = dayKey(it.at)
      if (k && day && k !== day) rows.push(<Divider key={`d-${key}`} label={dateLabel(it.at)} />)
      if (k) day = k
    }
    if (it.type === "user") rows.push(<UserBubble key={key} item={it} />)
    else if (it.type === "queued") { if (pending.has(idx)) rows.push(<UserBubble key={key} queued item={{ type: "user", line: it.line, text: it.text, origin: "panel", at: it.at }} />) }
    else if (it.type === "agent") rows.push(<AgentMessage key={key} markdown={it.markdown} frozen={idx < lastDivider} at={it.at} later={laterUsers(items, idx)} />)
    else if (it.type === "notice") rows.push(<Notice key={key} item={it} />)
    else if (it.type === "session") rows.push(<Divider key={key} label={sessionLabel(items[idx + 1])} />)
  }

  return (
    <div className="ag-wrap">
      <div className="ag-list" ref={box} onScroll={onScroll} data-testid="agent-list">
        {rows}
        {working && <WorkingIndicator title={runningTitle(items)} />}
      </div>
      {away && <button type="button" className="btn btn-sm ag-new" onClick={jump}>New messages</button>}
    </div>
  )
}
