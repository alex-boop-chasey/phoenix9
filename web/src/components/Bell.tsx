import { useEffect, useRef, useState } from "react"
import { Link } from "react-router"

import { Icon } from "@/components/Icon"
import { usePhoneWidth } from "@/lib/panelState"
import { fullWhen, shortWhen } from "@/lib/format"
import { useBell, useBellDismiss, useBellDismissAll } from "@/lib/queries"
import type { BellItem } from "@/lib/types"

/** The saved status report, shown in the home logs view. */
const REPORT_LINK = "/p/home/logs?log=reports%2Fstatus.md"

/** Desktop: hangs under the bell button. Phone: fixed under the top bar, 16px from both edges, as tall as the screen allows. */
const PANEL_DESKTOP = "absolute right-0 top-full mt-1 max-h-[min(70vh,calc(100dvh-4.5rem))] w-[min(22rem,calc(100vw-1rem))]"
const PANEL_PHONE = "bell-phone fixed left-4 right-4 top-[64px] max-h-[calc(100dvh-76px)]"

/** The top-bar bell: a button with the count that opens the list of what needs Alex. */
export function Bell() {
  const { data } = useBell()
  const dismiss = useBellDismiss()
  const dismissAll = useBellDismissAll()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const phone = usePhoneWidth()
  const count = data?.count ?? 0
  const items = data?.items ?? []

  useEffect(() => {
    const onOpen = () => setOpen(true)
    window.addEventListener("phoenix:open-bell", onOpen)
    return () => window.removeEventListener("phoenix:open-bell", onOpen)
  }, [])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false)
        button.current?.focus()
      }
    }
    const onClick = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener("keydown", onKey)
    document.addEventListener("mousedown", onClick)
    return () => {
      document.removeEventListener("keydown", onKey)
      document.removeEventListener("mousedown", onClick)
    }
  }, [open])

  const onDismiss = (item: BellItem) => {
    dismiss.mutate(item)
    list.current?.focus()
  }

  const label = count ? `Needs you: ${count} ${count === 1 ? "thing" : "things"} waiting` : "Needs you: nothing waiting"
  return (
    <div ref={box} className="relative">
      <button ref={button} type="button" className="hbtn" aria-label={label} aria-haspopup="true" aria-expanded={open}
        title={count ? `${count} ${count === 1 ? "thing needs" : "things need"} you` : "Nothing needs you"} onClick={() => setOpen((o) => !o)}>
        <Icon name="bell-ringing" />
        {count > 0 && <span className="cnt" data-testid="bell-count">{count}</span>}
      </button>
      {open && (
        <div ref={list} tabIndex={-1} role="region" aria-label="What needs you" data-testid="bell-list"
          className={`${phone ? PANEL_PHONE : PANEL_DESKTOP} z-50 flex flex-col rounded-md border bg-card shadow-lg outline-none`}>
          {items.length >= 2 && (
            <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
              <span className="text-sm font-semibold">Needs you</span>
              <button type="button" className="rounded px-2 py-1 text-xs hover:bg-muted" onClick={() => dismissAll.mutate()}>
                Dismiss all
              </button>
            </div>
          )}
          <div className="flex min-h-0 flex-col gap-1 overflow-y-auto overscroll-contain p-2">
            {items.length === 0 ? <p className="p-2 text-sm">Nothing needs you.</p> : items.map((item) => (
              <BellRow key={item.id} item={item}
                onOpen={() => { dismiss.mutate(item); setOpen(false) }}
                onDismiss={() => onDismiss(item)}
                onAsk={() => { askAgentAbout(item); setOpen(false) }} />
            ))}
          </div>
          <div className="border-t px-3 py-2 text-xs">
            <Link to={REPORT_LINK} className="underline-offset-2 hover:underline" onClick={() => setOpen(false)}>Full report</Link>
          </div>
        </div>
      )}
    </div>
  )
}

/** Open the agent drawer and ask it about one row; only the row's id is sent (its words come from builds). */
function askAgentAbout(item: BellItem) {
  window.dispatchEvent(new CustomEvent("phoenix:open-agent", { detail: { message: `Tell me about bell item ${item.id}` } }))
}

/** One row: a link to its page (with title, time and detail) and Dismiss and Ask the agent buttons beside it. */
function BellRow({ item, onOpen, onDismiss, onAsk }: { item: BellItem; onOpen: () => void; onDismiss: () => void; onAsk: () => void }) {
  const when = shortWhen(item.since)
  return (
    <div className="flex items-start gap-1 rounded hover:bg-muted" data-testid="bell-row">
      <Link to={(item.page.hash ?? "#/").slice(1) || "/"} data-testid="bell-item" className="block min-w-0 flex-1 rounded p-2 text-left"
        onClick={onOpen}>
        <strong className="block text-sm [overflow-wrap:anywhere]">{item.title}</strong>
        {when ? <time className="block text-xs text-muted-foreground" dateTime={item.since} title={fullWhen(item.since)}
          data-testid="bell-when">{when}</time> : null}
        {item.detail ? <span className="line-clamp-3 break-words text-xs text-muted-foreground" title={item.detail}>{item.detail}</span> : null}
      </Link>
      <div className="flex shrink-0 flex-col items-end mt-1 mr-1">
        <button type="button" className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-card hover:text-foreground"
          aria-label={`Dismiss: ${item.title}`} title="Dismiss" onClick={onDismiss}>
          Dismiss
        </button>
        <button type="button" className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-card hover:text-foreground"
          aria-label={`Ask the agent about: ${item.title}`} title="Ask the agent" onClick={onAsk}>
          Ask the agent
        </button>
      </div>
    </div>
  )
}
