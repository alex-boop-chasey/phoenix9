// One conversation with the agent: the chat, cards, approvals, Stop and the message box (page and drawer).
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode, type SyntheticEvent } from "react"
import { useNavigate } from "react-router"

import { Button } from "@/components/ui/button"
import { ApprovalCard, SuggestionChips, makeGoTo } from "./approval"
import { COMPONENTS, ToolCall } from "./components"
import { FlowLine, flowFrom } from "./flowcard"
import type { PageParts } from "./pageContext"
import {
  AssistantRuntimeProvider, ComposerPrimitive, ThreadPrimitive, olderFlowSteps, useAgentNextRuntime,
  type CardItem, type ChatLine, type Frame,
} from "./runtime"

/** A message sent while the agent was still writing: it waits its turn on the service. */
export interface QueuedMessage { runId: string; text: string; thread: string; queued: boolean }

/** One typed card, drawn from its data. */
function Card({ card, older, onSend }: { card: CardItem; older?: boolean; onSend?: (message: string) => void }) {
  if (older) {
    const flow = flowFrom(card.data)
    return flow ? <FlowLine card={flow} /> : null
  }
  const Draw = COMPONENTS[card.component]
  return Draw ? <>{Draw({ data: card.data, tool: card.component, callId: card.toolCallId, onSend })}</> : null
}

/** What a conversation shows and does; everything after `onRunEnd` is for the drawer and may be left out. */
export interface ConversationProps {
  thread: string
  earlier: ChatLine[]
  earlierCards: CardItem[]
  follow?: { frames: Frame[] }
  onRunEnd: () => void
  /** Show the "Agent" heading (the drawer has its own). */
  heading?: boolean
  /** What Alex has open, sent with every message. */
  context?: PageParts
  /** A line shown just above the message box. */
  chip?: ReactNode
  /** Where go_to moves the dashboard (default: the router). */
  goTo?: (path: string) => void
  /** Messages waiting their turn, shown as "Queued". */
  queued?: QueuedMessage[]
  /** Turns on sending while the agent writes; called with each message the service took. */
  onQueued?: (item: QueuedMessage) => void
  /** Called when Alex presses Stop (the service drops the queue). */
  onStopped?: () => void
  /** Called once the conversation has a service id (a new chat gets one with its first message). */
  onThread?: (id: string) => void
  /** A message to send as soon as the conversation shows (once per key). */
  pending?: { key: number; text: string }
  onPendingSent?: (key: number) => void
}

/** One conversation: the chat, cards, approvals, Stop and the message box. */
export function Conversation(props: ConversationProps) {
  const { thread, earlier, earlierCards, follow, onRunEnd, heading = true, context, chip, goTo, queued = [], onQueued, onStopped, onThread, pending, onPendingSent } = props
  const navigate = useNavigate()
  const browserHandler = useMemo(() => makeGoTo(goTo ?? ((hash) => navigate(hash))), [goTo, navigate])
  const { runtime, agent, side } = useAgentNextRuntime(browserHandler, thread, follow)
  agent.context = context

  const allCards = useMemo(() => [...earlierCards, ...side.cards], [earlierCards, side.cards])
  const older = useMemo(() => olderFlowSteps(allCards), [allCards])

  const [wasRunning, setWasRunning] = useState(false)
  useEffect(() => {
    if (side.running) setWasRunning(true)
    else if (wasRunning) { setWasRunning(false); onRunEnd() }
  }, [side.running, wasRunning, onRunEnd])

  useEffect(() => {
    if (side.thread) onThread?.(side.thread)
  }, [side.thread, onThread])

  const say = (text: string) => runtime.thread.append({ role: "user", content: [{ type: "text", text }] })
  const queueing = !!onQueued && side.running

  /** Send a message while the agent writes: the service queues it, or says plainly why not. */
  const sendQueued = async (text: string) => {
    const got = await agent.send(text)
    if (!("error" in got)) onQueued?.({ runId: got.run_id, text, thread: agent.serviceThread, queued: got.queued })
  }

  // The message box stays usable while the agent writes: its Enter and Send go to the queue instead.
  const takeForQueue = (e: SyntheticEvent) => {
    if (!queueing) return
    e.preventDefault()
    e.stopPropagation()
    const text = runtime.thread.composer.getState().text.trim()
    if (!text) return
    runtime.thread.composer.setText("")
    void sendQueued(text)
  }
  const onKeyDownCapture = (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) takeForQueue(e)
  }

  const sentKey = useRef<number | null>(null)
  useEffect(() => {
    if (!pending || sentKey.current === pending.key) return
    sentKey.current = pending.key
    if (onQueued && side.running) void sendQueued(pending.text)
    else say(pending.text)
    onPendingSent?.(pending.key)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending])

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="flex flex-col gap-3">
        {heading && <h1>Agent</h1>}
        {[...earlier, ...(side.caught ?? [])].map((l) => <p key={l.id} data-role={l.role}>{l.text}</p>)}
        <ThreadPrimitive.Root>
          <ThreadPrimitive.Viewport className="flex flex-col gap-2">
            <ThreadPrimitive.Messages>
              {({ message }) => (
                <p data-role={message.role}>
                  {message.content.map((part, i) => (part.type === "text" ? <span key={i}>{part.text}</span> : null))}
                </p>
              )}
            </ThreadPrimitive.Messages>
          </ThreadPrimitive.Viewport>
        </ThreadPrimitive.Root>
        {(side.calls ?? []).filter((c) => c.running || !c.component).map((c) => <ToolCall key={c.toolCallId} call={c} />)}
        {allCards.map((c) => <Card key={c.toolCallId} card={c} older={older.has(c.toolCallId)} onSend={say} />)}
        {side.approvals.map((a) => (
          <ApprovalCard key={a.approvalId} item={a} onDecide={(d, confirm) => agent.decide(a.approvalId, d, confirm)} />
        ))}
        <SuggestionChips actions={side.suggestions} onSend={say} />
        {queued.length > 0 && (
          <ul className="flex flex-col gap-1" aria-label="Waiting to be answered" data-testid="agent-queued">
            {queued.map((q) => (
              <li key={q.runId} data-role="user" className="text-muted-foreground">
                <span className="badge b-info">Queued</span> {q.text}
              </li>
            ))}
          </ul>
        )}
        {side.refused && <p role="alert">{side.refused}</p>}
        {chip}
        <div onKeyDownCapture={onKeyDownCapture} onSubmitCapture={takeForQueue}>
          <ComposerPrimitive.Root className="flex gap-2">
            <ComposerPrimitive.Input className="input" placeholder="Ask the agent" aria-label="Message" />
            {queueing
              ? <Button variant="primary" type="submit">Send</Button>
              : <ComposerPrimitive.Send asChild><Button variant="primary">Send</Button></ComposerPrimitive.Send>}
            {side.running && <Button variant="secondary" onClick={() => { onStopped?.(); void agent.stop() }}>Stop</Button>}
          </ComposerPrimitive.Root>
        </div>
      </div>
    </AssistantRuntimeProvider>
  )
}
