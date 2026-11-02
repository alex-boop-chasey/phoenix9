import { useEffect, useRef } from "react"

import { Icon } from "@/components/Icon"

/** The Phoenix Agent side drawer (empty until phase 6). */
export function AgentDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const close = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (open) close.current?.focus()
  }, [open])
  return (
    <aside className={open ? "drawer open" : "drawer"} aria-label="Phoenix Agent" aria-hidden={!open}>
      <div className="dr-h">
        <span className="mark" style={{ width: 32, height: 32 }}><Icon name="flame" /></span>
        <h2 className="h2">Phoenix Agent</h2>
        <button ref={close} className="btn btn-ghost btn-icon" aria-label="Close Phoenix Agent" style={{ marginLeft: "auto" }} onClick={onClose}>
          <Icon name="x" />
        </button>
      </div>
      <div className="dr-b">
        <div className="empty">
          <span className="ec"><Icon name="flame" /></span>
          <b className="h3">Phoenix Agent (coming in phase 6)</b>
          <p className="small">
            Ask in plain words, for example “show me the projects that need me”. It will set the Projects filters and
            answer with clickable mini cards.
          </p>
        </div>
      </div>
      <div className="dr-f">
        <label className="sr" htmlFor="agentIn">Message</label>
        <input className="input" id="agentIn" placeholder="Message the Phoenix Agent" disabled />
        <button className="btn btn-primary" disabled>Send</button>
      </div>
    </aside>
  )
}
