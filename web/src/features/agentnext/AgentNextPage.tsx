// The /agent-next page: the chat on assistant-ui, with our own cards, approval buttons and page moves.
import { useCallback } from "react"
import { useNavigate } from "react-router"

import { Button } from "@/components/ui/button"
import { findRoute, routeHash } from "@/lib/routes"
import { ProjectCards } from "./ProjectCards"
import {
  AssistantRuntimeProvider, ComposerPrimitive, ThreadPrimitive, useAgentNextRuntime,
  type ApprovalItem, type CardItem,
} from "./runtime"

/** The cards we can draw, chosen by name; anything else is not drawn. */
const CARDS: Record<string, (props: { data: any }) => React.ReactNode> = {
  project_cards: ({ data }) => <ProjectCards projects={data?.projects ?? []} />,
}

/** One typed card, drawn from its data. */
function Card({ card }: { card: CardItem }) {
  const Draw = CARDS[card.component]
  return Draw ? <>{Draw({ data: card.data })}</> : null
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

/** The agent's chat, cards and approvals. */
export default function AgentNextPage() {
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
  const { runtime, agent, side } = useAgentNextRuntime(browserHandler)

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <div className="flex flex-col gap-3" data-testid="agent-next">
        <h1>Agent</h1>
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
        {side.cards.map((c) => <Card key={c.toolCallId} card={c} />)}
        {side.approvals.map((a) => (
          <ApprovalCard key={a.approvalId} item={a} onDecide={(d) => agent.decide(a.approvalId, d)} />
        ))}
        <ComposerPrimitive.Root className="flex gap-2">
          <ComposerPrimitive.Input className="input" placeholder="Ask the agent" aria-label="Message" />
          <ComposerPrimitive.Send asChild><Button variant="primary">Send</Button></ComposerPrimitive.Send>
        </ComposerPrimitive.Root>
      </div>
    </AssistantRuntimeProvider>
  )
}
