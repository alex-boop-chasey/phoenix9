/** The "Chat" part of a project's Settings tab: the chat's state in words, Sleep, "Start a fresh chat" and a quiet "Open in browser" link. */
import { useState } from "react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { relativeTime } from "@/lib/format"
import { useChat, useForgetChat, useSleepChat } from "@/lib/queries"
import type { ChatInfo } from "@/lib/types"

const WORDS = { none: "No chat yet", waking: "Waking…", awake: "Awake", working: "Awake, working", asleep: "Asleep" }

/** The chat's state in plain words, e.g. "Asleep, last used 3 hours ago". */
export function chatWords(chat: ChatInfo): string {
  const words = WORDS[chat.state] ?? chat.state
  if (chat.state !== "asleep" || !chat.last_active) return words
  return `${words}, last used ${relativeTime(new Date(chat.last_active * 1000).toISOString())}`
}

/** Chat state, a Sleep button while it is awake, "Start a fresh chat" (with a question) and the browser link when there is one. */
export function ChatSection({ name }: { name: string }) {
  const chat = useChat(name)
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState("")
  const handlers = {
    onSuccess: (result: { message: string }) => { setError(""); toast.success(result.message) },
    onError: (err: Error) => setError(err.message),
  }
  const sleep = useSleepChat()
  const forget = useForgetChat()

  if (!chat.data) return null
  const state = chat.data.state
  const awake = state === "awake" || state === "working"
  return (
    <div className="sect" id="sec-chat">
      <div className="sect-h">
        <h2 className="h2">Chat</h2>
        <span className="area"><Icon name="sliders-horizontal" />Chat</span>
      </div>
      <div className="swap">
        <span className="t"><b>{chatWords(chat.data)}</b></span>
        {(awake || sleep.isPending) && (
          <button type="button" className="btn btn-secondary btn-sm" disabled={sleep.isPending} onClick={() => sleep.mutate(name, handlers)}>
            {sleep.isPending && <Wheel />}
            {sleep.isPending ? "Putting the chat to sleep…" : "Sleep"}
          </button>
        )}
        {state !== "none" && (
          <button type="button" className="btn btn-secondary btn-sm" disabled={forget.isPending} onClick={() => setAsking(true)}>Start a fresh chat</button>
        )}
      </div>
      {chat.data.web_url && (
        <p className="help"><a href={chat.data.web_url} target="_blank" rel="noreferrer">Open in browser</a></p>
      )}
      {error && <p role="alert" className="help">{error}</p>}
      <ConfirmDialog open={asking} onOpenChange={setAsking} title="Start a fresh chat?" confirmLabel="Forget saved chat"
        body="Forget this project's saved chat? The old conversation stays in your Claude app but Phoenix will no longer open it; pressing Chat starts a new one."
        onConfirm={() => forget.mutate(name, handlers)} />
    </div>
  )
}
