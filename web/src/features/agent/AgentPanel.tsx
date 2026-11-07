// The Agent panel: the slide-in on every dashboard page that shows the Phoenix agent's conversation.
import { useEffect, useRef, useState, type RefObject } from "react"

import { Icon } from "@/components/Icon"
import { useAgentMessages, useAgentStatus, type AgentState } from "@/features/agent/useAgent"
import { MessageList } from "@/features/agent/messages"
import { readWide, writeWide } from "@/features/agent/panelState"

const LOOK: Record<AgentState, { cls: string; word: string }> = {
  idle: { cls: "b-ok", word: "Idle" },
  working: { cls: "b-run", word: "Working…" },
  queued: { cls: "b-info", word: "Queued" },
  asleep: { cls: "", word: "Asleep" },
}

/** The small status pill in the panel header. */
function StatusPill() {
  const { data } = useAgentStatus()
  const messages = useAgentMessages().data
  if (!data) return null
  const look = LOOK[data.state]
  const waiting = (messages?.items ?? []).filter((i) => i.type === "queued" && i.pending).length
  const text = data.state === "queued" ? `Queued ${Math.max(waiting, 1)}` : look.word
  return <span className={`badge ${look.cls}`} data-testid="agent-state">{text}</span>
}

/** The slide-in Phoenix agent panel; focus goes to the message box on open and back to `opener` on close. */
export function AgentPanel({ open, onClose, opener }: { open: boolean; onClose: () => void; opener: RefObject<HTMLElement | null> }) {
  const { data: status } = useAgentStatus()
  const thread = useAgentMessages().data
  const [wide, setWide] = useState(readWide)
  const composer = useRef<HTMLTextAreaElement>(null)
  const wasOpen = useRef(open)

  useEffect(() => {
    if (open) composer.current?.focus()
    else if (wasOpen.current) opener.current?.focus()
    wasOpen.current = open
  }, [open, opener])

  const toggleWide = () => {
    setWide(!wide)
    writeWide(!wide)
  }

  return (
    <aside
      className={`drawer${open ? " open" : ""}${wide ? " wide" : ""}`}
      aria-label="Phoenix agent panel"
      aria-hidden={!open}
      data-testid="agent-panel"
    >
      <div className="dr-h">
        <span className="mark" style={{ width: 32, height: 32 }}><Icon name="flame" /></span>
        <h2 className="h2">Phoenix agent</h2>
        <StatusPill />
        <div className="dr-tools">
          {status?.app_url && (
            <a className="btn btn-ghost btn-icon" href={status.app_url} target="_blank" rel="noopener noreferrer" aria-label="Open in Claude app" title="Open in Claude app">
              <Icon name="arrow-up-right" />
            </a>
          )}
          <button className="btn btn-ghost btn-icon" aria-label="History" aria-haspopup="menu" title="History">
            <Icon name="clock" />
          </button>
          <button className="btn btn-ghost btn-icon dr-wide" aria-label="Wide" aria-pressed={wide} title="Wide" onClick={toggleWide}>
            <Icon name={wide ? "caret-right" : "caret-left"} />
          </button>
          <button className="btn btn-ghost btn-icon" aria-label="Close" title="Close (Esc)" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
      </div>
      <div className="dr-b">
        <MessageList items={thread?.items ?? []} state={status?.state} />
      </div>
      <div className="dr-f">
        <label className="sr" htmlFor="agentIn">Message</label>
        <textarea ref={composer} className="input" id="agentIn" rows={2} placeholder="Message the Phoenix agent" />
      </div>
    </aside>
  )
}
