// The message box of the Phoenix agent panel: grows to 6 lines, Enter sends, context rides along.
import { useLayoutEffect, useState, type KeyboardEvent, type Ref } from "react"
import { toast } from "sonner"

import { Icon } from "@/components/Icon"
import { useNextContext } from "@/features/agent/ContextChip"
import { rememberTold } from "@/features/agent/pageContext"
import { useAgentMessages, useAgentStatus, useSendToAgent, useSuggestions } from "@/features/agent/useAgent"

const MAX_LINES = 6
const LINE_PX = 20
const PAD_PX = 16
const SLASH_HINT = "Commands like /clear don't work from here: use the Claude app."

/** Grow the box to fit its text, up to six lines. */
function fit(el: HTMLTextAreaElement | null) {
  if (!el) return
  const max = MAX_LINES * LINE_PX + PAD_PX
  el.style.height = "auto"
  el.style.height = `${Math.min(el.scrollHeight, max)}px`
  el.style.maxHeight = `${max}px`
}

/** The footer message box with its send button, hints and the still-queued question. */
export function Composer({ contextOn = true, inputRef, offline = false }: { contextOn?: boolean; inputRef?: Ref<HTMLTextAreaElement>; offline?: boolean }) {
  const [text, setText] = useState("")
  const [ask, setAsk] = useState(false)
  const [el, setEl] = useState<HTMLTextAreaElement | null>(null)
  const status = useAgentStatus().data
  const items = useAgentMessages().data?.items ?? []
  const next = useNextContext()
  const send = useSendToAgent()
  const fresh = !items.some((i) => i.type === "user")
  const news = useSuggestions().data?.suggestions.filter((s) => !s.shown).length ?? 0
  const asleep = status?.state === "asleep" || offline
  const stillQueued = items.some((i) => i.type === "queued" && i.pending)
  const blank = !text.trim()

  useLayoutEffect(() => fit(el), [el, text])

  const setRefs = (node: HTMLTextAreaElement | null) => {
    setEl(node)
    if (typeof inputRef === "function") inputRef(node)
    else if (inputRef) (inputRef as { current: HTMLTextAreaElement | null }).current = node
  }

  const go = () => {
    const sendsContext = contextOn && Object.keys(next.parts).length > 0
    const parts = fresh && news > 0 ? { ...next.parts, suggestions: news } : next.parts
    const body = sendsContext || parts !== next.parts ? { text, context: parts } : { text }
    setAsk(false)
    send.mutate(body, {
      onSuccess: () => {
        if (contextOn) rememberTold(next.session, next.page.context)
        setText("")
      },
      onError: (e) => toast.error(e instanceof Error ? e.message : "The message was not sent."),
    })
  }

  const trySend = () => {
    if (asleep || blank || send.isPending) return
    if (stillQueued && !ask) return setAsk(true)
    go()
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key !== "Enter" || e.shiftKey || e.nativeEvent.isComposing) return
    e.preventDefault()
    trySend()
  }

  return (
    <div className="ag-comp">
      {send.isPending && <div className="ag-prog" role="progressbar" aria-label="Sending" />}
      {text.startsWith("/") && <p className="ag-hint" role="status">{SLASH_HINT}</p>}
      {asleep && <p className="ag-reason" id="agentWhy">{offline ? "Phoenix is not answering, so messages can't be sent right now." : "The Phoenix agent is asleep, so messages can't be sent right now."}</p>}
      {ask && (
        <div className="ag-queued" role="group" aria-label="Still queued">
          <span>Still queued. Send anyway?</span>
          <button className="btn btn-sm" onClick={go}>Send anyway</button>
          <button className="btn btn-ghost btn-sm" onClick={() => setAsk(false)}>Cancel</button>
        </div>
      )}
      <div className="ag-row">
        <label className="sr" htmlFor="agentIn">Message</label>
        <textarea
          ref={setRefs}
          className="input"
          id="agentIn"
          rows={1}
          value={text}
          disabled={asleep}
          aria-describedby={asleep ? "agentWhy" : undefined}
          placeholder="Message the Phoenix agent"
          onChange={(e) => { setText(e.target.value); setAsk(false) }}
          onKeyDown={onKey}
        />
        <button className="btn btn-primary btn-icon" aria-label="Send" title="Send (Enter)" disabled={asleep || blank || send.isPending} onClick={trySend}>
          <Icon name="paper-plane" />
        </button>
      </div>
    </div>
  )
}
