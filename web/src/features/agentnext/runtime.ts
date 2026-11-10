// The only file that imports assistant-ui's runtime. It joins our agent service's stream (AG-UI events over SSE)
// to the chat, and carries the typed cards, the approval pauses and the browser actions beside the text.
import { AbstractAgent, type BaseEvent, type RunAgentInput } from "@ag-ui/client"
import { AssistantRuntimeProvider, ComposerPrimitive, ThreadPrimitive } from "@assistant-ui/react"
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui"
import { Observable, type Subscriber } from "rxjs"
import { useMemo, useSyncExternalStore } from "react"

import { apiBase } from "@/lib/api"

/** A typed card the agent asked the panel to draw, chosen by component name. */
export interface CardItem { toolCallId: string; component: string; data: unknown }

/** A change waiting for Alex's answer: the tool and its exact inputs. */
export interface ApprovalItem { approvalId: string; toolName: string; input: unknown; decision: "pending" | "approve" | "deny" }

/** What the browser answers to a browser action such as go_to. */
export type BrowserAnswer = Record<string, unknown>

/** The things beside the text that the page draws. */
export interface SideState { cards: CardItem[]; approvals: ApprovalItem[] }

type Frame = { number: number; event: Record<string, any> }
type Wait = Promise<void>

/** Where the agent service's calls go, under the dashboard's own address. */
function agentUrl(path: string): string {
  return new URL(`agent-next/${path}`, apiBase()).toString()
}

/** Read an SSE body into numbered events. */
async function* readFrames(res: Response): AsyncGenerator<Frame> {
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  for (;;) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done })
    let cut: number
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)
      const id = /^id: (\d+)$/m.exec(frame)
      const data = /^data: (.*)$/m.exec(frame)
      if (data) yield { number: id ? Number(id[1]) : 0, event: JSON.parse(data[1]!) }
    }
    if (done) return
  }
}

/** Our agent: sends the message, follows the stream, answers browser actions and waits for approvals. */
export class AgentNextAgent extends AbstractAgent {
  private seen = 0
  private side: SideState = { cards: [], approvals: [] }
  private listeners = new Set<() => void>()
  private deciders = new Map<string, (d: "approve" | "deny") => void>()
  serviceThread: string
  private threadReady: Promise<string> | null = null
  browserHandler: (name: string, args: Record<string, unknown>) => Promise<BrowserAnswer> = async () => ({
    ok: false, error: "This page cannot do that.",
  })

  constructor(thread = "") {
    super()
    this.serviceThread = thread
  }

  /** The current cards and approvals (a new object whenever they change). */
  getSide = (): SideState => this.side

  /** Call back whenever the cards or approvals change; returns the way to stop. */
  watch = (fn: () => void): (() => void) => {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }

  private setSide(next: SideState) {
    this.side = next
    this.listeners.forEach((fn) => fn())
  }

  /** Record Alex's answer to a pending approval; the paused run carries on. */
  decide(approvalId: string, decision: "approve" | "deny") {
    this.deciders.get(approvalId)?.(decision)
  }

  private async ensureThread(): Promise<string> {
    if (this.serviceThread) return this.serviceThread
    this.threadReady ??= this.post("threads", {}).then(async (res) => {
      this.serviceThread = (await res.json()).id
      return this.serviceThread
    })
    return this.threadReady
  }

  private post(path: string, body: unknown): Promise<Response> {
    return fetch(agentUrl(path), {
      method: "POST",
      headers: { "X-Phoenix": "1", "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  }

  run(input: RunAgentInput): Observable<BaseEvent> {
    return new Observable<BaseEvent>((sub) => {
      this.drive(input, sub).catch((err) => sub.error(err))
    })
  }

  private async drive(input: RunAgentInput, sub: Subscriber<BaseEvent>) {
    const last = [...input.messages].reverse().find((m) => m.role === "user")
    const text = typeof last?.content === "string" ? last.content : ""
    const id = await this.ensureThread()
    this.seen = 0
    await this.post(`threads/${id}/runs`, { message: text })
    for (;;) {
      const waits: Wait[] = []
      const final = await this.follow(id, sub, waits)
      if (final) return sub.complete()
      await Promise.all(waits)
    }
  }

  /** Follow the stream from where it stopped; returns true when the run ended. */
  private async follow(id: string, sub: Subscriber<BaseEvent>, waits: Wait[]): Promise<boolean> {
    const res = await fetch(agentUrl(`threads/${id}/stream?after=${this.seen}`), { headers: { "X-Phoenix": "1" } })
    const args = new Map<string, string>()
    const names = new Map<string, string>()
    for await (const { number, event } of readFrames(res)) {
      this.seen = Math.max(this.seen, number)
      if (event.type === "CUSTOM") {
        this.onCustom(event.name, event.value, waits, id)
        continue
      }
      sub.next(event as BaseEvent)
      if (event.type === "TOOL_CALL_START") names.set(event.toolCallId, event.toolCallName)
      if (event.type === "TOOL_CALL_ARGS") args.set(event.toolCallId, (args.get(event.toolCallId) ?? "") + event.delta)
      if (event.type === "TOOL_CALL_END" && event.toolCallId && names.get(event.toolCallId) === "go_to") {
        waits.push(this.runBrowserTool(id, event.toolCallId, "go_to", args.get(event.toolCallId) ?? "{}", sub))
      }
      if (event.type === "RUN_FINISHED" || event.type === "RUN_ERROR") return true
    }
    return false
  }

  private onCustom(name: string, value: any, waits: Wait[], threadId: string) {
    if (name === "component") {
      this.setSide({ ...this.side, cards: [...this.side.cards, value as CardItem] })
    } else if (name === "approval_request") {
      const item: ApprovalItem = { approvalId: value.approvalId, toolName: value.toolName, input: value.input, decision: "pending" }
      this.setSide({ ...this.side, approvals: [...this.side.approvals, item] })
      waits.push(new Promise<void>((resolve) => {
        this.deciders.set(item.approvalId, (decision) => {
          this.deciders.delete(item.approvalId)
          this.markDecided(item.approvalId, decision)
          this.post(`approvals/${item.approvalId}`, { decision }).then(() => resolve(), () => resolve())
        })
      }))
    }
    void threadId
  }

  private markDecided(approvalId: string, decision: "approve" | "deny") {
    const approvals = this.side.approvals.map((a) => (a.approvalId === approvalId ? { ...a, decision } : a))
    this.setSide({ ...this.side, approvals })
  }

  private async runBrowserTool(_id: string, callId: string, name: string, rawArgs: string, sub: Subscriber<BaseEvent>) {
    let args: Record<string, unknown> = {}
    try { args = JSON.parse(rawArgs) } catch { /* refused below by the handler */ }
    const result = await this.browserHandler(name, args)
    await this.post(`browser-results/${callId}`, { result })
    sub.next({ type: "TOOL_CALL_RESULT", messageId: `${callId}-result`, toolCallId: callId, content: JSON.stringify(result), role: "tool" } as unknown as BaseEvent)
  }
}

/** The chat runtime for the page (assistant-ui over our agent), plus the agent for cards and approvals. */
export function useAgentNextRuntime(browserHandler: AgentNextAgent["browserHandler"]) {
  const agent = useMemo(() => new AgentNextAgent(), [])
  agent.browserHandler = browserHandler
  const runtime = useAgUiRuntime({ agent })
  const side = useSyncExternalStore(agent.watch, agent.getSide)
  return { runtime, agent, side }
}

export { AssistantRuntimeProvider, ComposerPrimitive, ThreadPrimitive }
