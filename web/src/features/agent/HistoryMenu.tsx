// The History menu in the panel header: earlier conversations (start time and line count).
import { useEffect, useRef, useState } from "react"

import { Icon } from "@/components/Icon"
import { useAgentSessions } from "@/features/agent/useAgent"

/** A readable start time for a session row. */
export function startLabel(at: string): string {
  const d = new Date(at)
  return Number.isNaN(d.getTime()) ? at : d.toLocaleString([], { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })
}

/** The clock button and its list of earlier conversations; choosing one calls `onPick(session_id)`. */
export function HistoryMenu({ current, onPick }: { current: string | null | undefined; onPick: (id: string) => void }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const sessions = useAgentSessions(open)

  useEffect(() => {
    if (!open) return
    const off = (e: Event) => {
      if (e.type === "keydown" && (e as KeyboardEvent).key !== "Escape") return
      if (e.type === "mousedown" && box.current?.contains(e.target as Node)) return
      if (e.type === "keydown") e.stopPropagation()
      setOpen(false)
    }
    document.addEventListener("keydown", off, true)
    document.addEventListener("mousedown", off)
    return () => {
      document.removeEventListener("keydown", off, true)
      document.removeEventListener("mousedown", off)
    }
  }, [open])

  const earlier = (sessions.data ?? []).filter((s) => s.session_id !== current)

  return (
    <div className="ag-hist" ref={box}>
      <button className="btn btn-ghost btn-icon" aria-label="History" aria-haspopup="menu" aria-expanded={open} title="History" onClick={() => setOpen(!open)}>
        <Icon name="clock" />
      </button>
      {open && (
        <div className="ag-menu" role="menu" aria-label="Earlier conversations">
          {sessions.isPending && <p className="ag-menu-note">Loading…</p>}
          {sessions.isError && <p className="ag-menu-note">The history could not be read.</p>}
          {sessions.data && !earlier.length && <p className="ag-menu-note">No earlier conversations.</p>}
          {earlier.map((s) => (
            <button key={s.session_id} role="menuitem" className="ag-menu-item" onClick={() => { setOpen(false); onPick(s.session_id) }}>
              <span>{startLabel(s.started)}</span>
              <span className="ag-meta">{s.lines} lines</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
