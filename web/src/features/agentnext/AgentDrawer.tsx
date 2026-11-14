// The Agent drawer in the top bar: the new agent's conversation on every dashboard page, told which page Alex has open.
import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react"
import { useLocation } from "react-router"

import { Icon } from "@/components/Icon"
import { navigateKeepingPanel } from "@/lib/navigate"
import { usePhoneWidth } from "@/lib/panelState"
import { AllowanceBar } from "./Allowance"
import { Conversation, type QueuedMessage } from "./Conversation"
import { NotAnsweringCard } from "./NotAnswering"
import { contextToSend, lookingAt, readPageContext } from "./pageContext"
import type { ThreadInfo } from "./runtime"
import { rememberThread, useThreads } from "./useThreads"

/** A message to send when the drawer opens (from the `phoenix:open-agent` event); a new key sends again. */
export interface DrawerAsk { key: number; text: string }

/** Height of the top bar the drawer sits under. */
const TOP_BAR_PX = 60

/** While open on a phone: lock the page behind and size the drawer to the part of the screen above the keyboard. */
function usePhoneSheet(open: boolean, phone: boolean, panel: RefObject<HTMLElement | null>) {
  useEffect(() => {
    if (!open) return
    document.body.classList.add("agent-open")
    return () => document.body.classList.remove("agent-open")
  }, [open])

  useEffect(() => {
    const el = panel.current
    const vv = window.visualViewport
    if (!open || !phone || !el || !vv) return
    const fit = () => el.style.setProperty("--ag-vh", `${Math.max(vv.height + vv.offsetTop - TOP_BAR_PX, 0)}px`)
    fit()
    vv.addEventListener("resize", fit)
    vv.addEventListener("scroll", fit)
    return () => {
      vv.removeEventListener("resize", fit)
      vv.removeEventListener("scroll", fit)
      el.style.removeProperty("--ag-vh")
    }
  }, [open, phone, panel])
}

/** Say when a conversation was last used, in plain words. */
function lastUsed(seconds: number): string {
  return seconds ? new Date(seconds * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "not yet"
}

/** The clock button and its list of earlier conversations; choosing one opens it. */
function HistoryMenu({ threads, current, onOpen, onShow }: { threads: ThreadInfo[]; current: string; onOpen: (id: string) => void; onShow: () => void }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const off = (e: Event) => {
      if (e.type === "keydown" && (e as globalThis.KeyboardEvent).key !== "Escape") return
      if (e.type === "mousedown" && box.current?.contains(e.target as Node)) return
      if (e.type === "keydown") e.stopPropagation()
      setOpen(false)
    }
    document.addEventListener("keydown", off, true)
    document.addEventListener("mousedown", off)
    return () => {
      document.removeEventListener("keydown", off, true)
      document.removeEventListener("mousedown", off)
    }
  }, [open])

  return (
    <div className="ag-hist" ref={box}>
      <button className="btn btn-ghost btn-icon" aria-label="History" aria-haspopup="menu" aria-expanded={open} title="History"
        onClick={() => { if (!open) onShow(); setOpen(!open) }}>
        <Icon name="clock" />
      </button>
      {open && (
        <div className="ag-menu" role="menu" aria-label="Earlier conversations">
          {!threads.length && <p className="ag-menu-note">No earlier conversations.</p>}
          {threads.map((t) => (
            <button key={t.id} role="menuitem" className="ag-menu-item" aria-current={t.id === current ? "true" : undefined}
              onClick={() => { setOpen(false); onOpen(t.id) }}>
              <span>{t.title || "New conversation"}</span>
              <span className="ag-meta">{lastUsed(t.last_used)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * The slide-in agent drawer; focus goes to the message box on open and back to `opener` on close.
 * `onNews` is called while it is closed when a reply finishes or an approval starts waiting.
 */
export function AgentDrawer({ open, onClose, opener, ask, onNews }: {
  open: boolean; onClose: () => void; opener: RefObject<HTMLElement | null>; ask?: DrawerAsk | null; onNews?: () => void
}) {
  const [started, setStarted] = useState(open)
  useEffect(() => { if (open) setStarted(true) }, [open])
  const t = useThreads(started)
  const { current, opened, refresh, followQueued, recheck } = t
  const openRef = useRef(open)
  openRef.current = open
  const news = useCallback(() => { if (!openRef.current) onNews?.() }, [onNews])
  const [back, setBack] = useState(false)
  const onBack = useCallback(() => { setBack(true); recheck() }, [recheck])

  const aside = useRef<HTMLElement>(null)
  const phone = usePhoneWidth()
  usePhoneSheet(open, phone, aside)

  const { pathname, search } = useLocation()
  const parts = useMemo(() => readPageContext(pathname, search).context, [pathname, search])
  const context = useMemo(() => contextToSend(parts), [parts])

  // Messages sent while the agent writes; they stay listed until their turn starts.
  const [queued, setQueued] = useState<QueuedMessage[]>([])
  const queuedRef = useRef(queued)
  queuedRef.current = queued
  const threadRef = useRef(current)
  useEffect(() => { if (current) threadRef.current = current }, [current])

  const onThread = useCallback((id: string) => {
    threadRef.current = id
    rememberThread(id)
  }, [])
  const followNext = useCallback(async (id: string, ids: string[]) => {
    const started = await followQueued(id, ids)
    setQueued((q) => q.filter((m) => !started.has(m.runId)))
  }, [followQueued])
  const onRunEnd = useCallback(() => {
    news()
    void refresh()
    const waiting = queuedRef.current.filter((m) => m.thread === threadRef.current)
    if (waiting.length) void followNext(threadRef.current, waiting.map((m) => m.runId))
  }, [refresh, followNext, news])
  const onQueued = useCallback((m: QueuedMessage) => {
    if (m.queued) setQueued((q) => [...q, m])
    else void followNext(m.thread, [m.runId])  // the reply ended meanwhile: this one started at once
  }, [followNext])
  const forget = () => setQueued([])

  // A message from the open-agent event is sent once, after the conversation has loaded.
  const [sentAsk, setSentAsk] = useState<number | null>(null)
  const pending = ask && ask.key !== sentAsk && t.ready && !t.problem ? ask : undefined

  const wasOpen = useRef(open)
  useEffect(() => {
    if (open) aside.current?.querySelector<HTMLElement>("[aria-label=Message]")?.focus()
    else if (wasOpen.current) opener.current?.focus()
    wasOpen.current = open
  }, [open, opener, t.ready, opened])

  return (
    <aside
      ref={aside}
      className={`drawer${open ? " open" : ""}`}
      aria-label="Phoenix agent panel"
      aria-hidden={!open}
      data-testid="agent-panel"
    >
      <div className="dr-h">
        <span className="mark" style={{ width: 32, height: 32 }}><Icon name="flame" /></span>
        <h2 className="h2">Agent</h2>
        <div className="dr-tools">
          {!t.problem && (
            <button className="btn btn-ghost btn-icon" aria-label="New conversation" title="New conversation" onClick={() => { forget(); t.fresh() }}>
              <Icon name="plus" />
            </button>
          )}
          <HistoryMenu threads={t.threads} current={current} onShow={() => void refresh()} onOpen={(id) => { forget(); void t.open(id) }} />
          <a className="btn btn-ghost btn-icon" href="#/agent-next" aria-label="Open full page" title="Open full page" onClick={onClose}>
            <Icon name="arrow-up-right" />
          </a>
          <button className="btn btn-ghost btn-icon" aria-label="Close" title="Close (Esc)" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
      </div>
      <div className="dr-b" style={{ display: "block", textAlign: "left", overflowY: "auto" }}>
        {t.problem && (t.reason
          ? <NotAnsweringCard key={t.reason} reason={t.reason} message={t.problem} onBack={onBack} />
          : <p role="alert">{t.problem}</p>)}
        {back && !t.problem && t.ready && <p role="status" className="ag-empty">The agent is back.</p>}
        {started && !t.problem && (
          <Conversation
            key={`${current}-${opened}`}
            thread={current}
            earlier={t.earlier}
            earlierCards={t.earlierCards}
            follow={t.follow}
            onRunEnd={onRunEnd}
            heading={false}
            context={context}
            chip={<p className="ag-ctx" data-testid="agent-context">{lookingAt(context ?? {})}</p>}
            goTo={navigateKeepingPanel}
            queued={queued.filter((m) => !threadRef.current || m.thread === threadRef.current)}
            onQueued={onQueued}
            onStopped={forget}
            onThread={onThread}
            pending={pending}
            onPendingSent={setSentAsk}
            onApprovalWaiting={news}
          />
        )}
      </div>
      <div className="dr-f">
        <div className="flex-1"><AllowanceBar allowance={t.allowance} /></div>
      </div>
    </aside>
  )
}
