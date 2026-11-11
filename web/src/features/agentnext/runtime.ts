// The only file that imports assistant-ui's runtime. It joins our agent service's stream (AG-UI events over SSE)
// to the chat, and carries the typed cards, the approval pauses and the browser actions beside the text.
import { AbstractAgent, type BaseEvent, type RunAgentInput } from "@ag-ui/client"
import { AssistantRuntimeProvider, ComposerPrimitive, ThreadPrimitive } from "@assistant-ui/react"
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui"
import { Observable, type Subscriber } from "rxjs"
import { useEffect, useMemo, useSyncExternalStore } from "react"

import { apiBase } from "@/lib/api"
import type { ToolCallItem } from "./components"

/** A typed card the agent asked the panel to draw, chosen by component name. */
export interface CardItem { toolCallId: string; component: string; data: unknown }

/** A change waiting for Alex's answer: the tool and its exact inputs. */
export interface ApprovalItem { approvalId: string; toolName: string; input: unknown; description?: string; confirmText?: string; decision: "pending" | "approve" | "deny" }

/** What the browser answers to a browser action such as go_to. */
export type BrowserAnswer = Record<string, unknown>

/** The things beside the text that the page draws. */
export interface SideState { cards: CardItem[]; approvals: ApprovalItem[]; running: boolean; calls?: ToolCallItem[]; suggestions?: unknown; caught?: ChatLine[] }

/** How long to wait before following the stream again after the connection dropped. */
const RETRY_MS = 300

type FollowState = { args: Map<string, string>; names: Map<string, string> }
export type Frame = { number: number; event: Record<string, any> }
type Wait = Promise<void>

/** One earlier message of an opened conversation. */
export interface ChatLine { id: string; role: "user" | "assistant"; text: string }

/** A conversation in the history list. */
export interface ThreadInfo { id: string; title: string; last_used: number }

/** How much of the month's allowance is used, in words only. */
export interface Allowance { used_share: number; state: "plenty" | "low" | "used_up" }

/** Read from the agent service; null when it cannot answer. */
export async function agentGet<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(agentUrl(path), { headers: { "X-Phoenix": "1" } })
    return res.ok ? ((await res.json()) as T) : null
  } catch {
    return null
  }
}

/** Whether the agent can be used; if not, the plain message to show in place of the chat. */
export async function agentAvailable(): Promise<{ ok: true } | { ok: false; message: string }> {
  const down = "The agent isn't available right now."
  try {
    const res = await fetch(agentUrl("status"), { headers: { "X-Phoenix": "1" } })
    const body = await res.json().catch(() => ({}))
    const said = typeof body?.message === "string" ? body.message : null
    if (!res.ok || body?.running === false) return { ok: false, message: said ?? down }
    if (body?.key_present === false) return { ok: false, message: said ?? "The agent has no API key yet." }
    return { ok: true }
  } catch {
    return { ok: false, message: down }
  }
}

/** Start a new empty conversation on the service and return its id. */
export async function newThread(): Promise<string | null> {
  const res = await fetch(agentUrl("threads"), {
    method: "POST", headers: { "X-Phoenix": "1", "Content-Type": "application/json" }, body: "{}",
  })
  return res.ok ? ((await res.json()) as { id: string }).id : null
}

/** Turn a stored conversation's events into plain chat lines. */
export function linesFromEvents(events: { event: Record<string, any> }[]): ChatLine[] {
  const lines: ChatLine[] = []
  const open = new Map<string, ChatLine>()
  for (const { event: e } of events) {
    if (e.type === "CUSTOM" && e.name === "user_message") lines.push({ id: e.value.id, role: "user", text: e.value.text })
    else if (e.type === "TEXT_MESSAGE_START") {
      const line: ChatLine = { id: e.messageId, role: "assistant", text: "" }
      open.set(e.messageId, line)
      lines.push(line)
    } else if (e.type === "TEXT_MESSAGE_CONTENT") {
      const line = open.get(e.messageId)
      if (line) line.text += e.delta
    }
  }
  return lines
}

/** The cards a stored conversation drew, in order (for a thread opened after it finished). */
export function cardsFromEvents(events: { event: Record<string, any> }[]): CardItem[] {
  const out: CardItem[] = []
  for (const { event: e } of events) {
    const v = e.value
    if (e.type === "CUSTOM" && e.name === "component" && v && typeof v.toolCallId === "string" && typeof v.component === "string") out.push(v as CardItem)
  }
  return out
}

/** Mark every FlowCard that has a newer one of the same flow as older (to be shown as one line). */
export function olderFlowSteps(cards: CardItem[]): Set<string> {
  const newest = new Map<string, string>()
  const flowOf = (c: CardItem) => (c.component === "FlowCard" && c.data && typeof (c.data as any).flow === "string" ? ((c.data as any).flow as string) : null)
  for (const c of cards) {
    const f = flowOf(c)
    if (f) newest.set(f, c.toolCallId)
  }
  const older = new Set<string>()
  for (const c of cards) {
    const f = flowOf(c)
    if (f && newest.get(f) !== c.toolCallId) older.add(c.toolCallId)
  }
  return older
}

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

/** The tools the browser itself carries out, without a card. */
const BROWSER_ACTIONS = ["go_to", "open_bell"]

/** Our agent: sends the message, follows the stream, answers browser actions and waits for approvals. */
export class AgentNextAgent extends AbstractAgent {
  private seen = 0
  private kept: Frame[] | null = null
  private side: SideState = { cards: [], approvals: [], running: false }
  private listeners = new Set<() => void>()
  private deciders = new Map<string, (d: "approve" | "deny", confirm?: string) => void>()
  serviceThread: string
  private threadReady: Promise<string> | null = null
  browserHandler: (name: string, args: Record<string, unknown>) => Promise<BrowserAnswer> = async () => ({
    ok: false, error: "This page cannot do that.",
  })

  constructor(thread = "") {
    super()
    this.serviceThread = thread
  }

  /** Stop the reply that is going now. */
  async stop() {
    if (!this.serviceThread) return
    await this.post(`threads/${this.serviceThread}/stop`, {})
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
  decide(approvalId: string, decision: "approve" | "deny", confirm?: string) {
    this.deciders.get(approvalId)?.(decision, confirm)
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
    this.setSide({ ...this.side, running: true, suggestions: undefined })
    try {
      const id = await this.ensureThread()
      this.seen = 0
      await this.post(`threads/${id}/runs`, { message: text })
      for (;;) {
        const waits: Wait[] = []
        const final = await this.follow(id, sub, waits)
        if (final) return sub.complete()
        await Promise.all(waits)
        if (!waits.length) await new Promise((r) => setTimeout(r, RETRY_MS))
      }
    } finally {
      this.setSide({ ...this.side, running: false })
    }
  }

  /** Follow the stream from where it stopped; returns true when the run ended, false when the connection dropped. */
  private async follow(id: string, sub: Subscriber<BaseEvent>, waits: Wait[]): Promise<boolean> {
    const ctx: FollowState = { args: new Map(), names: new Map() }
    try {
      const res = await fetch(agentUrl(`threads/${id}/stream?after=${this.seen}`), { headers: { "X-Phoenix": "1" } })
      if (!res.ok || !res.body) return false
      for await (const { number, event } of readFrames(res)) {
        if (number > 0 && number <= this.seen) continue
        this.seen = Math.max(this.seen, number)
        if (this.handle(id, event, sub, waits, ctx)) return true
      }
    } catch {
      return false
    }
    return false
  }

  /** Take in one event; returns true when it ends the run. */
  private handle(id: string, event: Record<string, any>, sub: Subscriber<BaseEvent>, waits: Wait[], ctx: FollowState): boolean {
    if (this.kept) {
      this.kept.push({ number: 0, event })
      this.setSide({ ...this.side, caught: linesFromEvents(this.kept) })
    }
    if (event.type === "CUSTOM") {
      this.onCustom(event.name, event.value, waits, id)
      return false
    }
    sub.next(event as BaseEvent)
    if (event.type === "TOOL_CALL_START") {
      ctx.names.set(event.toolCallId, event.toolCallName)
      this.setSide({ ...this.side, calls: [...(this.side.calls ?? []), { toolCallId: event.toolCallId, toolName: event.toolCallName, running: true }] })
    }
    if (event.type === "TOOL_CALL_RESULT") this.finishCall(event.toolCallId)
    if (event.type === "TOOL_CALL_ARGS") ctx.args.set(event.toolCallId, (ctx.args.get(event.toolCallId) ?? "") + event.delta)
    if (event.type === "TOOL_CALL_END" && event.toolCallId && BROWSER_ACTIONS.includes(ctx.names.get(event.toolCallId) ?? "")) {
      waits.push(this.runBrowserTool(id, event.toolCallId, ctx.names.get(event.toolCallId) ?? "", ctx.args.get(event.toolCallId) ?? "{}", sub))
    }
    return event.type === "RUN_FINISHED" || event.type === "RUN_ERROR"
  }

  /**
   * Catch up with a run that is still going (after a reload or reopening): show what the thread holds so far,
   * then follow the stream from the last event number until the run ends, reconnecting when the line drops.
   */
  async attach(id: string, stored: Frame[]) {
    this.serviceThread = id
    this.seen = stored.reduce((n, f) => Math.max(n, f.number), 0)
    this.kept = []
    const sub = { next: () => {} } as unknown as Subscriber<BaseEvent>
    this.setSide({ ...this.side, running: true })
    try {
      const waits: Wait[] = []
      const ctx: FollowState = { args: new Map(), names: new Map() }
      for (const f of stored) if (this.handle(id, f.event, sub, waits, ctx)) return
      for (;;) {
        if (await this.follow(id, sub, waits)) return
        await Promise.all(waits.splice(0))
        await new Promise((r) => setTimeout(r, RETRY_MS))
      }
    } finally {
      this.kept = null
      this.setSide({ ...this.side, running: false })
    }
  }

  private onCustom(name: string, value: any, waits: Wait[], threadId: string) {
    if (name === "component") {
      const card = value as CardItem
      const calls = (this.side.calls ?? []).map((c) => (c.toolCallId === card.toolCallId ? { ...c, running: false, component: card.component, data: card.data } : c))
      this.setSide({ ...this.side, cards: [...this.side.cards, card], calls })
    } else if (name === "suggestions") {
      this.setSide({ ...this.side, suggestions: (value as { actions?: unknown })?.actions })
    } else if (name === "approval_request") {
      const item: ApprovalItem = { approvalId: value.approvalId, toolName: value.toolName, input: value.input,
        description: typeof value.description === "string" ? value.description : undefined,
        confirmText: typeof value.confirm_text === "string" ? value.confirm_text : undefined, decision: "pending" }
      this.setSide({ ...this.side, approvals: [...this.side.approvals, item] })
      waits.push(new Promise<void>((resolve) => {
        this.deciders.set(item.approvalId, (decision, confirm) => {
          this.deciders.delete(item.approvalId)
          this.markDecided(item.approvalId, decision)
          this.post(`approvals/${item.approvalId}`, confirm === undefined ? { decision } : { decision, confirm }).then(() => resolve(), () => resolve())
        })
      }))
    }
    void threadId
  }

  private finishCall(toolCallId: string) {
    const calls = (this.side.calls ?? []).map((c) => (c.toolCallId === toolCallId ? { ...c, running: false } : c))
    this.setSide({ ...this.side, calls })
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
export function useAgentNextRuntime(browserHandler: AgentNextAgent["browserHandler"], thread = "", follow?: { frames: Frame[] }) {
  const agent = useMemo(() => new AgentNextAgent(thread), [thread])
  agent.browserHandler = browserHandler
  useEffect(() => {
    if (follow) void agent.attach(thread, follow.frames)
  }, [agent, thread, follow])
  const runtime = useAgUiRuntime({ agent })
  const side = useSyncExternalStore(agent.watch, agent.getSide)
  return { runtime, agent, side }
}

export { AssistantRuntimeProvider, ComposerPrimitive, ThreadPrimitive }
