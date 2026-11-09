/** The "Chat connection" part of a project's Settings tab: the chat's state, Sleep and Disconnect. */
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Icon } from "@/components/Icon"
import { api } from "@/lib/api"
import { useChat } from "@/lib/queries"
import type { ChatState } from "@/lib/types"

const WORDS: Record<ChatState, string> = { off: "Off", sleeping: "Asleep", starting: "Running", live: "Running", working: "Running" }

/** Chat state, a Sleep button while it runs, and a Disconnect button (with a question) unless it is off. */
export function ChatSection({ name }: { name: string }) {
  const chat = useChat(name)
  const qc = useQueryClient()
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState("")
  const done = (words: string) => () => {
    setError("")
    toast.success(words)
    void qc.invalidateQueries({ queryKey: ["chat", name] })
    void qc.invalidateQueries({ queryKey: ["projects"] })
  }
  const failed = (err: Error) => setError(err.message)
  const sleep = useMutation({ mutationFn: () => api.sleepChat(name), onSuccess: done("The chat is asleep. It wakes when you open it."), onError: failed })
  const off = useMutation({ mutationFn: () => api.offChat(name), onSuccess: done("The chat is disconnected."), onError: failed })

  if (!chat.data || chat.data.state === "off") return null
  const state = chat.data.state
  return (
    <div className="sect" id="sec-chat">
      <div className="sect-h">
        <h2 className="h2">Chat connection</h2>
        <span className="area"><Icon name="sliders-horizontal" />Chat</span>
      </div>
      <div className="swap">
        <span className="t"><b>{WORDS[state]}</b></span>
        {WORDS[state] === "Running" && (
          <button type="button" className="btn btn-secondary btn-sm" disabled={sleep.isPending} onClick={() => sleep.mutate()}>Sleep</button>
        )}
        <button type="button" className="btn btn-secondary btn-sm" disabled={off.isPending} onClick={() => setAsking(true)}>Disconnect</button>
      </div>
      {error && <p role="alert" className="help">{error}</p>}
      <ConfirmDialog open={asking} onOpenChange={setAsking} title="Disconnect chat?" confirmLabel="Disconnect"
        body="Disconnect this project's chat? The chat's link stops working; pressing Chat later makes a new connection."
        onConfirm={() => off.mutate()} />
    </div>
  )
}
