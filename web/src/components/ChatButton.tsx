// The Chat button: opens the project's chat conversation, with a dot showing its state.
import { useState } from "react"

import { chatLink } from "@/lib/chatLink"
import { useOpenChat } from "@/lib/queries"
import type { ChatInfo, ChatState } from "@/lib/types"

const TIPS: Partial<Record<ChatState, string>> = {
  sleeping: "asleep: it wakes when you write to it",
  off: "off: pressing Chat starts a fresh conversation",
}

/** An outlined Chat button for a project (compact = the small sidebar size), with a state dot and an "Open in browser instead" link after pressing. */
export function ChatButton({ project, chat, compact = false }: { project: string; chat: ChatInfo | null; compact?: boolean }) {
  const open = useOpenChat()
  const [webUrl, setWebUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const state: ChatState = chat?.state ?? "off"
  const showDot = state !== "off"

  function press() {
    setError(null)
    open.mutate(project, {
      onSuccess: (result) => {
        setWebUrl(result.web_url)
        if (result.bridge_session_id) window.open(chatLink(result.bridge_session_id, navigator.userAgent))
      },
      onError: (err) => setError(err instanceof Error ? err.message : String(err)),
    })
  }

  return (
    <span className="chatbtn">
      <button type="button" className={compact ? "btn btn-secondary btn-sm" : "btn btn-secondary"} title={TIPS[state]} disabled={open.isPending} onClick={press}>
        {open.isPending ? "Starting chat…" : "Chat"}
        {showDot && <i className={`chatdot chatdot-${state}`} aria-hidden="true" />}
      </button>
      {webUrl && (
        <a className="chatweb" href={webUrl} target="_blank" rel="noreferrer">Open in browser instead</a>
      )}
      {error && <span role="alert" className="chaterr">{error}</span>}
    </span>
  )
}
