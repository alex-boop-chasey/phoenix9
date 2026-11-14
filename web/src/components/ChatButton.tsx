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

/** An outlined Chat button for a project with a state dot (its space always kept, so every Chat button is the same size); pressing again reopens the same chat. */
export function ChatButton({ project, chat }: { project: string; chat: ChatInfo | null }) {
  const open = useOpenChat()
  const state = useChatState(project, chat)
  const [pressedFrom, setPressedFrom] = useState<ChatState>("none")
  const [appLink, setAppLink] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  function press() {
    setError(null)
    // Already open and awake: open the same link straight away (a phone may block a link opened after waiting).
    if (appLink && (state === "awake" || state === "working")) {
      window.open(appLink)
      return
    }
    setPressedFrom(state)
    open.mutate(project, {
      onSuccess: (result) => {
        const app = result.bridge_session_id ? chatLink(result.bridge_session_id, navigator.userAgent) : null
        setAppLink(app)
        if (app) window.open(app)
      },
      onError: (err) => setError(err instanceof Error ? err.message : String(err)),
    })
  }

  const label = pressedFrom === "none" ? "Starting chat…" : "Waking chat…"
  return (
    <span className="chatbtn">
      <button type="button" className="btn btn-secondary" title={TIPS[state]} disabled={open.isPending} onClick={press}>
        {open.isPending && <Wheel />}
        <span className="chatlbl">{open.isPending ? label : "Chat"}</span>
        <i className={`chatdot chatdot-${state}`} aria-hidden="true" />
      </button>
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
