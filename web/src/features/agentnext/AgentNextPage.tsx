// The /agent-next page: the chat on assistant-ui, with our own cards, approval buttons and page moves.
import { useCallback, useEffect, useState } from "react"
import { useNavigate } from "react-router"

import { Button } from "@/components/ui/button"
import { findRoute, routeHash } from "@/lib/routes"
import { AllowanceBar } from "./Allowance"
import { History } from "./History"
import { COMPONENTS, ToolCall } from "./components"
import {
  AssistantRuntimeProvider, ComposerPrimitive, ThreadPrimitive, agentGet, linesFromEvents, useAgentNextRuntime,
  type Allowance, type ApprovalItem, type CardItem, type ChatLine, type ThreadInfo,
} from "./runtime"

/** The cards we can draw, chosen by name; anything else is not drawn. */

/** One typed card, drawn from its data. */
function Card({ card }: { card: CardItem }) {
  const Draw = COMPONENTS[card.component]
  return Draw ? <>{Draw({ data: card.data, tool: card.component })}</> : null
}

/** A change waiting for Alex: what it will do, with Approve and Deny. */
export function ApprovalCard({ item, onDecide }: { item: ApprovalItem; onDecide: (d: "approve" | "deny") => void }) {
  return (
    <section className="card" aria-label="Approval needed" data-testid="approval-card">
      <h3>The agent wants to make a change</h3>
      <p>{item.toolName}</p>
      <pre className="text-xs">{JSON.stringify(item.input, null, 2)}</pre>
      {item.decision === "pending" ? (
        <div className="flex gap-2">
          <Button variant="primary" onClick={() => onDecide("approve")}>Approve</Button>
          <Button variant="secondary" onClick={() => onDecide("deny")}>Deny</Button>
        </div>
      ) : (
        <p>{item.decision === "approve" ? "Approved." : "Denied."}</p>
      )}
    </section>
  )
}

/** The agent's page: history and allowance beside one open conversation. */
export default function AgentNextPage() {
  const [threads, setThreads] = useState<ThreadInfo[]>([])
  const [allowance, setAllowance] = useState<Allowance | null>(null)
  const [current, setCurrent] = useState("")
  const [earlier, setEarlier] = useState<ChatLine[]>([])
  const [opened, setOpened] = useState(0)

  const refresh = useCallback(async () => {
    const list = await agentGet<{ threads: ThreadInfo[] }>("threads")
    if (list) setThreads(list.threads)
    const spend = await agentGet<Allowance>("spend")
    if (spend) setAllowance(spend)
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  const open = async (id: string) => {
    const got = await agentGet<{ events: { event: Record<string, any> }[] }>(`threads/${id}`)
    if (!got) return
    setEarlier(linesFromEvents(got.events))
    setCurrent(id)
    setOpened((n) => n + 1)
  }
  const fresh = () => {
    setEarlier([])
    setCurrent("")
    setOpened((n) => n + 1)
  }

  return (
    <div className="flex gap-4" data-testid="agent-next">
      <aside className="flex w-64 shrink-0 flex-col gap-4">
        <History threads={threads} current={current} onOpen={open} onNew={fresh} />
        <AllowanceBar allowance={allowance} />
      </aside>
      <div className="min-w-0 flex-1">
        <Conversation key={`${current}-${opened}`} thread={current} earlier={earlier} onRunEnd={refresh} />
      </div>
    </div>
  )
}

/** One conversation: the chat, cards, approvals, Stop and the message box. */
function Conversation({ thread, earlier, onRunEnd }: { thread: string; earlier: ChatLine[]; onRunEnd: () => void }) {
  const navigate = useNavigate()
  const browserHandler = useCallback(async (name: string, args: Record<string, unknown>) => {
    if (name !== "go_to") return { ok: false, error: "This page cannot do that." }
    const page = typeof args.page === "string" ? args.page : ""
    const params = (args.params ?? {}) as Record<string, unknown>
    if (!findRoute(page)) return { ok: false, error: "That page does not exist, so I did not go there." }
    const hash = routeHash(page, params)
    if (!hash) return { ok: false, error: "That page does not exist, so I did not go there." }
    navigate(hash.slice(1))
    return { ok: true, page }
  }, [navigate])
  const { runtime, agent, side } = useAgentNextRuntime(browserHandler, thread)

  const [wasRunning, setWasRunning] = useState(false)
  useEffect(() => {
    if (side.running) setWasRunning(true)
    else if (wasRunning) { setWasRunning(false); onRunEnd() }
  }, [side.running, wasRunning, onRunEnd])

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="flex flex-col gap-3">
        <h1>Agent</h1>
        {earlier.map((l) => <p key={l.id} data-role={l.role}>{l.text}</p>)}
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
        {side.cards.map((c) => <Card key={c.toolCallId} card={c} />)}
        {side.approvals.map((a) => (
          <ApprovalCard key={a.approvalId} item={a} onDecide={(d) => agent.decide(a.approvalId, d)} />
        ))}
        <ComposerPrimitive.Root className="flex gap-2">
          <ComposerPrimitive.Input className="input" placeholder="Ask the agent" aria-label="Message" />
          <ComposerPrimitive.Send asChild><Button variant="primary">Send</Button></ComposerPrimitive.Send>
          {side.running && <Button variant="secondary" onClick={() => void agent.stop()}>Stop</Button>}
        </ComposerPrimitive.Root>
      </div>
    </AssistantRuntimeProvider>
  )
}
