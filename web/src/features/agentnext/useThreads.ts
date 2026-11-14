// The conversation list, the allowance and the open conversation, shared by the /agent-next page and the drawer.
import { useCallback, useEffect, useState } from "react"

import {
  agentAvailable, agentGet, cardsFromEvents, lastRunStart, linesFromEvents, startedRuns,
  type Allowance, type CardItem, type NotAnswering, type ChatLine, type Frame, type ThreadInfo,
} from "./runtime"

/** The browser's memory of the last conversation, shared by the page and the drawer so both show the same chat. */
export const LAST_THREAD = "agent-next-thread"

type Stored = { events: Frame[]; running?: boolean }

/** How long to wait before looking again for a queued message that has not started yet. */
const QUEUE_LOOK_MS = 300
/** How many times to look before leaving the queued message to the next reply's end. */
const QUEUE_LOOKS = 10

/** Remember the last conversation; does nothing when storage is off. */
export function rememberThread(id: string) {
  try {
    localStorage.setItem(LAST_THREAD, id)
  } catch { /* storage is off */ }
}

/** The last conversation, or "" when none is remembered. */
function lastThread(): string {
  try {
    return localStorage.getItem(LAST_THREAD) ?? ""
  } catch {
    return ""
  }
}

/** History, allowance and the open conversation; `active` false waits (the drawer loads on first open). */
export function useThreads(active = true) {
  const [threads, setThreads] = useState<ThreadInfo[]>([])
  const [allowance, setAllowance] = useState<Allowance | null>(null)
  const [current, setCurrent] = useState("")
  const [earlier, setEarlier] = useState<ChatLine[]>([])
  const [earlierCards, setEarlierCards] = useState<CardItem[]>([])
  const [opened, setOpened] = useState(0)
  const [follow, setFollow] = useState<{ frames: Frame[] } | undefined>(undefined)
  const [problem, setProblem] = useState<string | null>(null)
  const [reason, setReason] = useState<NotAnswering | null>(null)
  const [checks, setChecks] = useState(0)
  const [ready, setReady] = useState(false)

  const refresh = useCallback(async () => {
    const list = await agentGet<{ threads: ThreadInfo[] }>("threads")
    if (list && Array.isArray(list.threads)) setThreads(list.threads)
    const spend = await agentGet<Allowance>("spend")
    if (spend && typeof spend.state === "string") setAllowance(spend)
  }, [])

  /** Show a stored conversation: finished runs as earlier lines and cards, a run still going replayed and followed. */
  const show = useCallback((id: string, got: Stored) => {
    const cut = got.running ? lastRunStart(got.events) : got.events.length
    const before = got.events.slice(0, cut)
    setEarlier(linesFromEvents(before))
    setEarlierCards(cardsFromEvents(before))
    setFollow(got.running ? { frames: got.events.slice(cut) } : undefined)
    setCurrent(id)
    rememberThread(id)
    setOpened((n) => n + 1)
  }, [])

  const open = useCallback(async (id: string) => {
    const got = await agentGet<Stored>(`threads/${id}`)
    if (got && Array.isArray(got.events)) show(id, got)
  }, [show])

  /**
   * After a reply ends with messages still queued: wait for the next one to start, then follow it.
   * Returns the run ids the conversation has started (so the caller can stop showing them as queued).
   */
  const followQueued = useCallback(async (id: string, waiting: string[]): Promise<Set<string>> => {
    for (let look = 0; look < QUEUE_LOOKS; look++) {
      const got = await agentGet<Stored>(`threads/${id}`)
      if (got && Array.isArray(got.events)) {
        const started = startedRuns(got.events)
        if (got.running || waiting.every((r) => started.has(r))) {
          show(id, got)
          return started
        }
      }
      await new Promise((r) => setTimeout(r, QUEUE_LOOK_MS))
    }
    return new Set()
  }, [show])

  useEffect(() => {
    if (!active) return
    let gone = false
    void agentAvailable().then(async (got) => {
      if (gone) return
      setProblem(got.ok ? null : got.message)
      setReason(got.ok ? null : got.reason)
      if (got.ok) {
        void refresh()
        const last = lastThread()
        if (last) await open(last)
      }
      if (!gone) setReady(true)
    })
    return () => { gone = true }
  }, [active, refresh, open, checks])

  /** Ask the agent again whether it answers (after a restart); loads the conversation when it does. */
  const recheck = useCallback(() => setChecks((n) => n + 1), [])

  const fresh = useCallback(() => {
    try {
      localStorage.removeItem(LAST_THREAD)
    } catch { /* storage is off */ }
    setFollow(undefined)
    setEarlier([])
    setEarlierCards([])
    setCurrent("")
    setOpened((n) => n + 1)
  }, [])

  return { threads, allowance, current, earlier, earlierCards, opened, follow, problem, reason, ready, refresh, open, fresh, followQueued, recheck }
}
