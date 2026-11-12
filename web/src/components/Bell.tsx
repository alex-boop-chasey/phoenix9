import { useEffect, useRef, useState } from "react"
import { Link } from "react-router"

import { Icon } from "@/components/Icon"
import { useBell } from "@/lib/queries"

/** The top-bar bell: a button with the count that opens the list of what needs Alex. */
export function Bell() {
  const { data } = useBell()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const button = useRef<HTMLButtonElement>(null)
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

  const label = count ? `Needs you: ${count} ${count === 1 ? "thing" : "things"} waiting` : "Needs you: nothing waiting"
  return (
    <div ref={box} className="relative">
      <button ref={button} type="button" className="hbtn" aria-label={label} aria-haspopup="true" aria-expanded={open}
        title={count ? `${count} ${count === 1 ? "thing needs" : "things need"} you` : "Nothing needs you"} onClick={() => setOpen((o) => !o)}>
        <Icon name="bell-ringing" />
        {count > 0 && <span className="cnt" data-testid="bell-count">{count}</span>}
      </button>
      {open && (
        <div role="region" aria-label="What needs you" data-testid="bell-list"
          className="absolute right-0 top-full z-50 mt-1 flex max-h-[70vh] w-[min(22rem,calc(100vw-1rem))] flex-col gap-1 overflow-y-auto rounded-md border bg-card p-2 shadow-lg">
          {items.length === 0 ? <p className="p-2 text-sm">Nothing needs you.</p> : items.map((item) => (
            <Link key={item.id} to={(item.page.hash ?? "#/").slice(1) || "/"} data-testid="bell-item" className="block rounded p-2 text-left hover:bg-muted"
              onClick={() => setOpen(false)}>
              <strong className="block text-sm">{item.title}</strong>
              {item.detail ? <span className="block text-xs text-muted-foreground">{item.detail}</span> : null}
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
