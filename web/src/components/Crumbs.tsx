import { Fragment } from "react"
import { Link, useLocation, useSearchParams } from "react-router"

import { Icon } from "@/components/Icon"

export interface Crumb {
  label: string
  to?: string
}

const TABS: Record<string, string> = { overview: "Overview", build: "Build", logs: "Logs", settings: "Settings" }

/** The breadcrumb trail for a route (the last item has no link). */
export function crumbsFor(pathname: string): Crumb[] {
  const parts = pathname.split("/").filter(Boolean).map((s) => decodeURIComponent(s))
  if (parts.length === 0) return [{ label: "Projects" }]
  if (parts[0] === "new") return [{ label: "Projects", to: "/" }, { label: "New project" }]
  if (parts[0] === "import") return [{ label: "Projects", to: "/" }, { label: "Import" }]
  if (parts[0] === "settings") return [{ label: "Phoenix settings" }]
  if (parts[0] === "styles") return [{ label: "Phoenix settings", to: "/settings" }, { label: "Style reference" }]
  if (parts[0] === "p" && parts[1]) {
    const name = parts[1]
    const base = `/p/${encodeURIComponent(name)}`
    const tab = parts[2]
    const out: Crumb[] = [{ label: "Projects", to: "/" }]
    if (!tab) return [...out, { label: name }]
    out.push({ label: name, to: `${base}/overview` })
    out.push({ label: TABS[tab] ?? tab })
    return out
  }
  return [{ label: "Projects", to: "/" }]
}

/** Breadcrumbs above the page content; the first item is always the Projects link (current on the projects page). */
export function Crumbs() {
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const items = crumbsFor(pathname)
  if (pathname === "/settings") {
    const tab = params.get("tab")
    if (tab === "services" || tab === "models" || tab === "updates") {
      items[0] = { label: "Phoenix settings", to: "/settings" }
      items.push({ label: tab.charAt(0).toUpperCase() + tab.slice(1) })
    }
  }
  const rest = items[0]?.label === "Projects" ? items.slice(1) : items
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      <Link className="crumbs-home" to="/" aria-current={pathname === "/" ? "page" : undefined}>
        <Icon name="squares-four" size="sm" />
        Projects
      </Link>
      {rest.map((c, i) => (
        <Fragment key={i}>
          <span aria-hidden="true">/</span>
          {c.to ? <Link to={c.to}>{c.label}</Link> : <span aria-current="page">{c.label}</span>}
        </Fragment>
      ))}
    </nav>
  )
}
