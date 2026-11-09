// Data hooks for the Phoenix agent panel: status, the cached conversation, its live stream, and sending.
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query"
import { useEffect } from "react"

import { apiBase, get, post } from "@/lib/api"

/** How often the panel re-reads messages when the live stream is not connected. */
export const AGENT_POLL_MS = 4000
const STATUS_MS = 3000
const THREAD_GC_MS = 60 * 60 * 1000
const RETRY_STREAM_AFTER_POLLS = 5
const PAGE_LIMIT = 1000

export type AgentState = "asleep" | "idle" | "working" | "queued"

/** What the agent is doing now (`app_url` is present only when the Claude app can open it). */
export interface AgentStatus {
  state: AgentState
  pid: number | null
  session_id: string | null
  name: string
  app_url?: string
}

export type ActionStatus = "running" | "ok" | "error"

export interface UserItem { type: "user"; line: number; text: string; origin: string; at: string }
export interface AgentTextItem { type: "agent"; line: number; markdown: string; at: string }
export interface ActionItem {
  type: "action"; line: number; id: string; tool: string; title: string; input_summary: string
  status: ActionStatus; excerpt?: string; done_line?: number
}
export interface ThinkingItem { type: "thinking"; line: number; duration_s: number; at: string }
export interface QueuedItem { type: "queued"; line: number; text: string; pending: boolean; at: string }
export interface NoticeItem { type: "notice"; line: number; text: string }
export interface SessionItem { type: "session"; line: number; session_id: string }

export type AgentItem = UserItem | AgentTextItem | ActionItem | ThinkingItem | QueuedItem | NoticeItem | SessionItem

/** A stream `update` frame: an action already shown has finished. */
export interface AgentUpdate {
  type: "update"; id: string; line: number; status: ActionStatus; excerpt?: string
}

export interface AgentMessages {
  items: AgentItem[]
  unknown: number
  last_line: number
  session_id: string | null
}

export interface AgentSessionRow { session_id: string; started: string; lines: number }

export interface AgentContext { page?: string; project?: string; run?: string; suggestions?: number }
export interface AgentSendBody { text: string; context?: AgentContext }
export interface AgentSendResult { sent: boolean; at: string; after_line: number }

/** React Query keys for the agent data, so every hook invalidates the same entries. */
export const agentKeys = {
  status: () => ["agent", "status"] as const,
  messages: (session: string) => ["agent", "messages", session] as const,
  sessions: () => ["agent", "sessions"] as const,
  earlier: (session: string) => ["agent", "earlier", session] as const,
}

const sessionKey = (id: string | null | undefined) => id ?? "none"

/** The agent's state, refreshed every few seconds. */
export function useAgentStatus() {
  return useQuery({
    queryKey: agentKeys.status(),
    queryFn: () => get<AgentStatus>("agent"),
    refetchInterval: STATUS_MS,
  })
}

/** The conversation of the current session; kept in the cache across panel open and close. */
export function useAgentMessages() {
  const status = useAgentStatus()
  const session = status.data ? sessionKey(status.data.session_id) : undefined
  return useQuery({
    queryKey: agentKeys.messages(session ?? ""),
    queryFn: () => get<AgentMessages>("agent/messages", { limit: PAGE_LIMIT }),
    enabled: session !== undefined,
    staleTime: Infinity,
    gcTime: THREAD_GC_MS,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  })
}

/** The list of past conversations, newest first. */
export function useAgentSessions(enabled = true) {
  return useQuery({
    queryKey: agentKeys.sessions(),
    queryFn: () => get<AgentSessionRow[]>("agent/sessions"),
    enabled,
  })
}

/** Add items we do not have yet (by line) to a thread. */
export function appendItems(thread: AgentMessages, items: AgentItem[], lastLine?: number): AgentMessages {
  const have = new Set(thread.items.map((i) => i.line))
  const fresh = items.filter((i) => !have.has(i.line))
  const top = Math.max(thread.last_line, lastLine ?? 0, ...fresh.map((i) => i.line))
  if (!fresh.length && top === thread.last_line) return thread
  return { ...thread, items: [...thread.items, ...fresh], last_line: top }
}

/** Patch the action with this id (status, excerpt) from an update frame. */
export function applyUpdate(thread: AgentMessages, up: AgentUpdate): AgentMessages {
  let hit = false
  const items = thread.items.map((i) => {
    if (i.type !== "action" || i.id !== up.id) return i
    hit = true
    return { ...i, status: up.status, excerpt: up.excerpt ?? i.excerpt, done_line: up.line > i.line ? up.line : i.done_line }
  })
  return hit ? { ...thread, items } : thread
}

/** A new thread that starts with a session divider. */
export function freshThread(sessionId: string): AgentMessages {
  return { items: [{ type: "session", line: 0, session_id: sessionId }], unknown: 0, last_line: 0, session_id: sessionId }
}

function streamUrl(after: number): string {
  const url = new URL("agent/stream", apiBase())
  url.searchParams.set("after", String(after))
  return url.toString()
}

function parse<T>(m: MessageEvent): T | null {
  try {
    return JSON.parse(m.data as string) as T
  } catch {
    return null
  }
}

/** The conversation moved to another session: show it fresh and point the status at it. */
function switchSession(qc: QueryClient, sessionId: string) {
  qc.setQueryData<AgentMessages>(agentKeys.messages(sessionKey(sessionId)), (old) => old ?? freshThread(sessionId))
  qc.setQueryData<AgentStatus>(agentKeys.status(), (old) => (old ? { ...old, session_id: sessionId } : old))
}

/** Follow the live stream into the cached conversation; poll every 4 s while the stream is broken. */
export function useAgentStream(enabled: boolean) {
  const qc = useQueryClient()
  const status = useAgentStatus()
  // Only trust a status fetched since this panel opened: a cached one may name a session that has ended.
  const session = status.isFetchedAfterMount && status.data ? sessionKey(status.data.session_id) : undefined
  const loaded = useAgentMessages().data !== undefined

  useEffect(() => {
    if (!enabled || session === undefined || !loaded) return
    let sid = session
    let stopped = false
    let source: EventSource | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    const thread = () => qc.getQueryData<AgentMessages>(agentKeys.messages(sid))
    const edit = (fn: (t: AgentMessages) => AgentMessages) => {
      qc.setQueryData<AgentMessages>(agentKeys.messages(sid), (old) => (old ? fn(old) : old))
    }

    const onSession = (id: string) => {
      sid = sessionKey(id)
      switchSession(qc, id)
    }

    const connect = () => {
      if (stopped) return
      if (typeof EventSource === "undefined") return startPolling()
      source = new EventSource(streamUrl(thread()?.last_line ?? 0))
      source.addEventListener("item", (m) => {
        const item = parse<AgentItem>(m as MessageEvent)
        if (item && typeof item.line === "number") edit((t) => appendItems(t, [item]))
      })
      source.addEventListener("update", (m) => {
        const up = parse<AgentUpdate>(m as MessageEvent)
        if (up) edit((t) => applyUpdate(t, up))
      })
      source.addEventListener("session", (m) => {
        const frame = parse<{ session_id: string }>(m as MessageEvent)
        if (frame?.session_id) onSession(frame.session_id)
      })
      source.onerror = () => {
        source?.close()
        source = null
        startPolling()
      }
    }

    const refetchAll = async () => {
      const page = await get<AgentMessages>("agent/messages", { limit: PAGE_LIMIT })
      if (page.session_id && sessionKey(page.session_id) !== sid) onSession(page.session_id)
      qc.setQueryData<AgentMessages>(agentKeys.messages(sessionKey(page.session_id)), page)
    }

    const pollOnce = async () => {
      const t = thread()
      if (t?.items.some((i) => i.type === "action" && i.status === "running")) return refetchAll()
      const page = await get<AgentMessages>("agent/messages", { after: t?.last_line ?? 0, limit: PAGE_LIMIT })
      if (page.session_id && sessionKey(page.session_id) !== sid) return refetchAll()
      edit((old) => appendItems(old, page.items, page.last_line))
    }

    const startPolling = () => {
      let polls = 0
      const tick = async () => {
        if (stopped) return
        try {
          await pollOnce()
        } catch {
          // keep trying; the next tick may work
        }
        if (stopped) return
        polls += 1
        if (polls >= RETRY_STREAM_AFTER_POLLS) return connect()
        timer = setTimeout(tick, AGENT_POLL_MS)
      }
      timer = setTimeout(tick, AGENT_POLL_MS)
    }

    connect()
    return () => {
      stopped = true
      source?.close()
      if (timer) clearTimeout(timer)
    }
  }, [enabled, session, loaded, qc])
}

/** Send a message to the agent; failures carry the server's plain reason. */
export function useSendToAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AgentSendBody) => post<AgentSendResult>("agent/send", body),
    onSettled: () => void qc.invalidateQueries({ queryKey: agentKeys.status() }),
  })
}

/** One earlier conversation, read-only (fetched once; it no longer changes). */
export function useEarlierSession(session: string | null) {
  return useQuery({
    queryKey: agentKeys.earlier(session ?? ""),
    queryFn: () => get<AgentMessages>("agent/messages", { limit: PAGE_LIMIT, session }),
    enabled: session !== null,
    staleTime: Infinity,
  })
}

/** Restart the Phoenix agent's service (the caller has already asked Alex to confirm). */
export function useRestartAgent() {
  return useMutation({
    mutationFn: () => post<{ restarted: boolean; unit: string }>("agent/restart", { confirm: true }),
  })
}

/** Save the agent's notes and start a new conversation (the caller has already asked Alex to confirm). */
export function useNewConversation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => post<{ started: boolean }>("agent/new", { confirm: true }),
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: agentKeys.status() }),
        qc.invalidateQueries({ queryKey: ["agent", "messages"] }),
        qc.invalidateQueries({ queryKey: agentKeys.sessions() }),
      ])
    },
  })
}

/** One report line worth a mention, as `/api/suggest` lists it. */
export interface Suggestion { key: string; text: string; section: string; attention: boolean; shown: boolean }

/** The strip's suggestions (up to three), re-read every minute. */
export function useSuggestions() {
  return useQuery({
    queryKey: ["agent", "suggest"] as const,
    queryFn: () => get<{ mode: string; suggestions: Suggestion[] }>("suggest"),
    refetchInterval: 60_000,
  })
}

/** Snooze or dismiss one suggestion, then re-read the list. */
export function useMarkSuggestion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ key, what }: { key: string; what: "snooze" | "dismiss" }) => post(`suggest/${encodeURIComponent(key)}/${what}`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agent", "suggest"] }),
  })
}
