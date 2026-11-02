// The "Add project" split button: the main part goes to Create new, the chevron opens two mini cards.
import { useEffect, useRef, useState } from "react"
import { Link } from "react-router"

import { Icon, type IconName } from "@/components/Icon"

const ITEMS: { to: string; icon: IconName; title: string; line: string }[] = [
  { to: "/new", icon: "plus-circle", title: "Create new", line: "Start fresh: empty, from a template, a GitHub repo or code on this server." },
  { to: "/import", icon: "download-simple", title: "Import", line: "Bring back a removed project, or a folder Phoenix doesn't list yet." },
]

/** Split button with a chevron menu of two mini cards (Create new, Import). */
export function AddProjectMenu() {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false) }
    document.addEventListener("click", away)
    document.addEventListener("keydown", esc)
    return () => { document.removeEventListener("click", away); document.removeEventListener("keydown", esc) }
  }, [open])

  return (
    <div className="split" ref={box}>
      <Link className="btn btn-primary" to="/new"><Icon name="plus" />Add project</Link>
      <button
        type="button" className="btn btn-primary chev" aria-haspopup="menu" aria-expanded={open}
        aria-label="More ways to add a project" onClick={() => setOpen((o) => !o)}
      >
        <Icon name="caret-down" />
      </button>
      <div className={`menu${open ? " open" : ""}`} role="menu">
        {ITEMS.map((it) => (
          <Link key={it.to} className="mini" role="menuitem" to={it.to} onClick={() => setOpen(false)} tabIndex={open ? 0 : -1}>
            <span className="ico"><Icon name={it.icon} /></span>
            <span className="t"><b>{it.title}</b><span>{it.line}</span></span>
          </Link>
        ))}
      </div>
    </div>
  )
}
