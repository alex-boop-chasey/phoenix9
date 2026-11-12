// The Chat button: opens the project's one chat conversation (waking it first), with a dot showing its state.
import { useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"

import { Wheel } from "@/components/Indicator"
import { chatLink } from "@/lib/chatLink"
import { keys, useChat, useOpenChat, useSleepChat } from "@/lib/queries"
import type { ChatInfo, ChatState } from "@/lib/types"

const TIPS: Record<ChatState, string> = {
  none: "No chat yet: press to start one",
  asleep: "Asleep: press to wake it",
  awake: "Awake",
  working: "Awake, working",
  waking: "Waking…",
}

/** The chat's state: the row's, or a fresher one fetched every 3 seconds while the row says it is waking. */
function useChatState(project: string, chat: ChatInfo | null): ChatState {
  const rowState: ChatState = chat?.state ?? "none"
  const waking = rowState === "waking"
  const polled = useChat(project, waking).data?.state
  const qc = useQueryClient()
  const done = waking && !!polled && polled !== "waking"
  useEffect(() => {
    if (!done) return
    void qc.invalidateQueries({ queryKey: keys.projects() })
    void qc.invalidateQueries({ queryKey: keys.project(project) })
  }, [done, qc, project])
  return waking && polled ? polled : rowState
}

/** An outlined Chat button for a project (compact = the small sidebar size), with a state dot; after pressing, "Open chat" and "Open in browser instead" links. */
export function ChatButton({ project, chat, compact = false }: { project: string; chat: ChatInfo | null; compact?: boolean }) {
  const open = useOpenChat()
  const state = useChatState(project, chat)
  const [pressedFrom, setPressedFrom] = useState<ChatState>("none")
  const [links, setLinks] = useState<{ app: string | null; web: string | null } | null>(null)
  const [error, setError] = useState<string | null>(null)

  function press() {
    setError(null)
    setPressedFrom(state)
    open.mutate(project, {
      onSuccess: (result) => {
        const app = result.bridge_session_id ? chatLink(result.bridge_session_id, navigator.userAgent) : null
        setLinks({ app, web: result.web_url })
        if (app) window.open(app)
      },
      onError: (err) => setError(err instanceof Error ? err.message : String(err)),
    })
  }

  const label = pressedFrom === "none" ? "Starting chat…" : "Waking chat…"
  return (
    <span className="chatbtn">
      <button type="button" className={compact ? "btn btn-secondary btn-sm" : "btn btn-secondary"} title={TIPS[state]} disabled={open.isPending} onClick={press}>
        {open.isPending && <Wheel />}
        {open.isPending ? label : "Chat"}
        {!open.isPending && state !== "none" && <i className={`chatdot chatdot-${state}`} aria-hidden="true" />}
      </button>
      {links?.app && <a className="chatweb" href={links.app} target="_blank" rel="noreferrer">Open chat</a>}
      {links?.web && <a className="chatweb" href={links.web} target="_blank" rel="noreferrer">Open in browser instead</a>}
      {error && <span role="alert" className="chaterr">{error}</span>}
    </span>
  )
}

/** The small "Sleep" text button beside Chat in the project header; shown only while the chat is awake or working. */
export function ChatSleepButton({ project, chat }: { project: string; chat: ChatInfo | null }) {
  const sleep = useSleepChat()
  const [error, setError] = useState<string | null>(null)
  const state = chat?.state ?? "none"
  if (!sleep.isPending && !error && state !== "awake" && state !== "working") return null

  function press() {
    setError(null)
    sleep.mutate(project, { onError: (err) => setError(err instanceof Error ? err.message : String(err)) })
  }

  return (
    <span className="chatbtn">
      <button type="button" className="btn btn-ghost btn-sm" disabled={sleep.isPending} onClick={press}
        title="Put the chat to sleep; it wakes when you press Chat">
        {sleep.isPending && <Wheel />}
        {sleep.isPending ? "Putting the chat to sleep…" : "Sleep"}
      </button>
      {error && <span role="alert" className="chaterr">{error}</span>}
    </span>
  )
}
