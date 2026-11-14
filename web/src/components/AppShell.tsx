import { useCallback, useEffect, useRef, useState, type ReactNode } from "react"
import { Link, matchPath, useLocation } from "react-router"

import { Bell } from "@/components/Bell"
import { Crumbs } from "@/components/Crumbs"
import { MainMenu } from "@/components/MainMenu"
import { ErrorBoundary } from "@/components/ErrorBoundary"
import { Icon } from "@/components/Icon"
import { ProjectList, ProjectSwitcher } from "@/components/ProjectSwitcher"
import { ThemeToggle } from "@/components/ThemeToggle"
import { AgentDrawer, type DrawerAsk } from "@/features/agentnext/AgentDrawer"
import { readOpen, usePhoneWidth, writeOpen } from "@/lib/panelState"
import { useLiveEvents } from "@/lib/live"
import { PAGE_SCROLLER_ID, scrollPageTop } from "@/lib/focus"
import { useInfo, useProjects } from "@/lib/queries"

/** A full-height frame: the header and the project switcher stay put, only the main content (#page) scrolls.
 * The header, project switcher, phone picker, agent drawer and the "well" around every route. */
export function AppShell({ children }: { children: ReactNode }) {
  const { data: info } = useInfo()
  const { data: projects } = useProjects()
  const { pathname } = useLocation()
  const [drawer, setDrawer] = useState(readOpen)
  const phone = usePhoneWidth()
  const [sheet, setSheet] = useState(false)
  const [wire, setWire] = useState(false)
  const [ask, setAsk] = useState<DrawerAsk | null>(null)
  const [unread, setUnread] = useState(false)
  const agentBtn = useRef<HTMLButtonElement>(null)
  useLiveEvents()

  const current = matchPath("/p/:name/*", pathname)?.params.name ?? matchPath("/p/:name", pathname)?.params.name
  const update = info?.update

  useEffect(() => {
    setWire(true)
    setSheet(false)
    scrollPageTop()
    const t = setTimeout(() => setWire(false), 600)
    return () => clearTimeout(t)
  }, [pathname])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setDrawer(false)
        setSheet(false)
      } else if (e.key === "." && e.ctrlKey) setDrawer((d) => !d)
    }
    // The event may carry a message to send (detail.message); the drawer sends it once it has loaded.
    const onOpen = (e: Event) => {
      setDrawer(true)
      const text = (e as CustomEvent<{ message?: unknown } | null>).detail?.message
      if (typeof text === "string" && text.trim()) setAsk((a) => ({ key: (a?.key ?? 0) + 1, text: text.trim() }))
    }
    document.addEventListener("keydown", onKey)
    window.addEventListener("phoenix:open-agent", onOpen)
    return () => {
      document.removeEventListener("keydown", onKey)
      window.removeEventListener("phoenix:open-agent", onOpen)
    }
  }, [])

  useEffect(() => writeOpen(drawer), [drawer])
  useEffect(() => { if (drawer) setUnread(false) }, [drawer])
  const onNews = useCallback(() => setUnread(true), [])

  const closeDrawer = () => setDrawer(false)

  return (
    <div className="app overflow-x-hidden">
      <header className="top">
        <div className="top-in gut">
        <Link className="brand" to="/" aria-label="Phoenix, go to projects">
          <span className="mark"><Icon name="flame" /></span>
          <span className="wordmark">
            <b>Phoenix</b>
            {info && <span title="Installed release">{info.label ?? info.version}</span>}
          </span>
        </Link>
        <div className="top-main">
        <MainMenu />
        <div className="top-r">
          {update?.supported && update.available && (
            <Link className="upd" to="/settings?tab=updates">
              <Icon name="arrow-circle-up" size="sm" />
              Update v{update.newest.replace(/^v/, "")}
            </Link>
          )}
          <button className="hbtn picker" aria-label="Choose a project" aria-haspopup="dialog" onClick={() => setSheet(true)}>
            <Icon name="squares-four" />
          </button>
          <Bell />
          <button ref={agentBtn} className="hbtn" aria-label="Phoenix agent" title="Phoenix agent (Ctrl .)" onClick={() => setDrawer(true)}>
            <Icon name="flame" />
            <span className="wtxt">Agent</span>
            {unread && <span className="cnt" data-testid="agent-unread" aria-label="New from the agent" role="img"
              style={{ minWidth: 10, width: 10, height: 10, padding: 0, top: 6, right: 4 }} />}
          </button>
          <ThemeToggle />
          <Link className="hbtn" to="/settings" aria-label="Settings" title="Phoenix settings">
            <Icon name="gear" />
            <span className="wtxt">Settings</span>
          </Link>
        </div>
        </div>
        </div>
      </header>

      <div className="shell gut">
        <ProjectSwitcher current={current} />
        <main id={PAGE_SCROLLER_ID} className={pathname.endsWith("/logs") ? "well console" : "well"}>
          <div className={wire ? "wire on" : "wire"} data-testid="wire" />
          <ErrorBoundary resetKey={pathname}>
            <Crumbs />
            {children}
          </ErrorBoundary>
        </main>
      </div>

      <div className={(drawer && phone) || sheet ? "scrim open" : "scrim"} data-testid="scrim" onClick={() => { closeDrawer(); setSheet(false) }} />
      <AgentDrawer open={drawer} onClose={closeDrawer} opener={agentBtn} ask={ask} onNews={onNews} />
      <div className={sheet ? "sheet open" : "sheet"} role="dialog" aria-label="Choose a project" aria-hidden={!sheet}>
        <div className="grab" />
        <div className="sw-head">
          <span>Projects</span>
          <Link to="/" onClick={() => setSheet(false)}>See all</Link>
        </div>
        <ProjectList rows={projects ?? []} current={current} onPick={() => setSheet(false)} />
      </div>
    </div>
  )
}
