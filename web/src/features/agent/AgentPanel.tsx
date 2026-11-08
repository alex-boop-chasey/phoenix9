// The Agent panel: the slide-in on every dashboard page that shows the Phoenix agent's conversation.
import { useEffect, useRef, useState, type RefObject } from "react"

import { Icon } from "@/components/Icon"
import { AsleepCard } from "@/features/agent/AsleepCard"
import { HistoryMenu } from "@/features/agent/HistoryMenu"
import { useAgentMessages, useAgentStatus, useEarlierSession, type AgentState } from "@/features/agent/useAgent"
import { Composer } from "@/features/agent/Composer"
import { ContextChip } from "@/features/agent/ContextChip"
import { MessageList } from "@/features/agent/messages"
import type { UiMove } from "@/features/agent/uiGo"
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
export function AgentPanel({ open, onClose, opener, moved = null, onBack }: {
  open: boolean; onClose: () => void; opener: RefObject<HTMLElement | null>; moved?: UiMove | null; onBack?: () => void
}) {
  const statusQ = useAgentStatus()
  const status = statusQ.data
  const threadQ = useAgentMessages()
  const thread = threadQ.data
  const [viewing, setViewing] = useState<string | null>(null)
  const earlier = useEarlierSession(viewing)
  const offline = statusQ.isError
  const asleep = status?.state === "asleep" && !offline
  const sendOnly = threadQ.isError && !offline && !asleep
  const [wide, setWide] = useState(readWide)
  const [contextOn, setContextOn] = useState(true)
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
          <HistoryMenu current={status?.session_id} onPick={setViewing} />
          <button className="btn btn-ghost btn-icon dr-wide" aria-label="Wide" aria-pressed={wide} title="Wide" onClick={toggleWide}>
            <Icon name={wide ? "caret-right" : "caret-left"} />
          </button>
          <button className="btn btn-ghost btn-icon" aria-label="Close" title="Close (Esc)" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
      </div>
      {offline && <p className="ag-banner" role="alert">Phoenix is not answering. The Phoenix agent will show here when it is back.</p>}
      {moved && (
        <p className="ag-banner" role="status" data-testid="agent-moved">
          <span>Moved to {moved.label}</span>
          <button className="btn btn-sm" onClick={onBack}>Back</button>
        </p>
      )}
      {viewing === null && !offline && !asleep && <ContextChip on={contextOn} onChange={setContextOn} />}
      {viewing !== null && (
        <div className="ag-banner" role="status">
          <span>An earlier conversation (read-only).</span>
          <button className="btn btn-sm" onClick={() => setViewing(null)}>Back to current</button>
        </div>
      )}
      {sendOnly && viewing === null && (
        <p className="ag-banner" role="status">The Phoenix agent's messages can't be read right now. You can still send it a message.</p>
      )}
      <div className="dr-b">{body()}</div>
      {viewing === null && (
        <div className="dr-f">
          <Composer contextOn={contextOn} inputRef={composer} offline={offline} />
        </div>
      )}
    </aside>
  )

  function body() {
    if (viewing !== null) {
      if (earlier.isError) return <p className="ag-empty">That conversation could not be read.</p>
      if (!earlier.data) return <Skeleton />
      return <MessageList items={earlier.data.items} />
    }
    if (offline) return <p className="ag-empty">Nothing to show while Phoenix is not answering.</p>
    if (!status) return <Skeleton />
    if (asleep) return <AsleepCard appUrl={status.app_url} />
    if (sendOnly) return <p className="ag-empty">Messages can't be shown.</p>
    if (!thread) return <Skeleton />
    return <MessageList items={thread.items} state={status.state} />
  }
}

/** Grey placeholder rows while the conversation loads. */
function Skeleton() {
  return (
    <div className="ag-skel" role="status" aria-label="Loading the conversation" data-testid="agent-skeleton">
      {[70, 45, 85, 55].map((w, n) => <span key={n} className="ag-skel-row" style={{ width: `${w}%` }} />)}
    </div>
  )
}
