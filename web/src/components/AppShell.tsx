import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react"
import { Link, matchPath, useLocation } from "react-router"

import { Bell } from "@/components/Bell"
import { Crumbs } from "@/components/Crumbs"
import { MainMenu } from "@/components/MainMenu"
import { ErrorBoundary } from "@/components/ErrorBoundary"
import { Icon } from "@/components/Icon"
import { ProjectList, ProjectSwitcher } from "@/components/ProjectSwitcher"
import { ThemeToggle } from "@/components/ThemeToggle"
import { AgentDrawer, type AgentSize, type DrawerAsk, type DrawerThread } from "@/features/agentnext/AgentDrawer"
import { agentGet, type ThreadInfo } from "@/features/agentnext/runtime"
import { readExpanded, readOpen, usePhoneWidth, writeExpanded, writeOpen } from "@/lib/panelState"
import { useLiveEvents } from "@/lib/live"
import { PAGE_SCROLLER_ID, scrollPageTop } from "@/lib/focus"
import { useInfo, useProjects } from "@/lib/queries"

/** How often the closed panel's button looks for an unread conversation. */
const UNREAD_LOOK_MS = 60_000

/** While the agent panel is closed: whether any conversation is unread, looked at once a minute and on window focus (never while the tab is hidden). */
function useUnreadThreads(closed: boolean): [boolean, (v: boolean) => void] {
  const [found, setFound] = useState(false)
  useEffect(() => {
    if (!closed) return
    let gone = false
    const look = async () => {
      if (document.hidden) return
      const list = await agentGet<{ threads: ThreadInfo[] }>("threads")
      if (!gone && list && Array.isArray(list.threads)) setFound(list.threads.some((t) => t.unread === true))
    }
    void look()
    const timer = setInterval(() => void look(), UNREAD_LOOK_MS)
    window.addEventListener("focus", look)
    return () => {
      gone = true
      clearInterval(timer)
      window.removeEventListener("focus", look)
    }
  }, [closed])
  return [found, setFound]
}

/** A full-height frame: the header and the project switcher stay put, only the main content (#page) scrolls.
 * The header, project switcher, phone picker, agent drawer and the "well" around every route. */
export function AppShell({ children }: { children: ReactNode }) {
  const { data: info } = useInfo()
  const { data: projects } = useProjects()
  const { pathname } = useLocation()
  const [drawer, setDrawer] = useState(readOpen)
  const [size, setSize] = useState<AgentSize>(() => (readExpanded() ? "full" : "drawer"))
  const phone = usePhoneWidth()
  const [sheet, setSheet] = useState(false)
  const [wire, setWire] = useState(false)
  const [ask, setAsk] = useState<DrawerAsk | null>(null)
  const [show, setShow] = useState<DrawerThread | null>(null)
  const [unread, setUnread] = useState(false)
  const [threadUnread, setThreadUnread] = useUnreadThreads(!drawer)
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

  // A layout effect, so the listener is there before a route's own effect sends the event (the old #/agent-next page does).
  useLayoutEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setDrawer(false)
        setSheet(false)
      } else if (e.key === "." && e.ctrlKey) setDrawer((d) => !d)
    }
    // The event may carry a message to send (detail.message), which the panel sends once it has loaded,
    // detail.thread to show that conversation (once the panel has loaded), and detail.size "full" to open it full screen.
    const onOpen = (e: Event) => {
      setDrawer(true)
      const detail = (e as CustomEvent<{ message?: unknown; size?: unknown; thread?: unknown } | null>).detail
      if (detail?.size === "full") setSize("full")
      const thread = detail?.thread
      if (typeof thread === "string" && thread) setShow((s) => ({ key: (s?.key ?? 0) + 1, id: thread }))
      const text = detail?.message
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
  useEffect(() => writeExpanded(size === "full"), [size])
  useEffect(() => {
    if (!drawer) return
    setUnread(false)
    setThreadUnread(false)
  }, [drawer, setThreadUnread])
  const onNews = useCallback(() => setUnread(true), [])

  const closeDrawer = () => setDrawer(false)
  // The Agent button opens the panel; while it is open (either size) it only puts the cursor in the message box.
  const onAgentButton = () => {
    if (!drawer) setDrawer(true)
    else document.querySelector<HTMLElement>("[data-testid=agent-panel] [aria-label=Message]")?.focus()
  }

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
          <button ref={agentBtn} className="hbtn" aria-label="Phoenix agent" title="Phoenix agent (Ctrl .)" onClick={onAgentButton}>
            <Icon name="flame" />
            <span className="wtxt">Agent</span>
            {(unread || threadUnread) && <span className="cnt" data-testid="agent-unread" aria-label="New from the agent" role="img"
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
      <AgentDrawer open={drawer} onClose={closeDrawer} opener={agentBtn} ask={ask} show={show} onNews={onNews} size={size} onSize={setSize} />
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
