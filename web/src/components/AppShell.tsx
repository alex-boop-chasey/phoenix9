import { useEffect, useRef, useState, type ReactNode } from "react"
import { Link, matchPath, useLocation } from "react-router"

import { AgentDrawer } from "@/components/AgentDrawer"
import { Crumbs } from "@/components/Crumbs"
import { Icon } from "@/components/Icon"
import { ProjectList, ProjectSwitcher } from "@/components/ProjectSwitcher"
import { ThemeToggle } from "@/components/ThemeToggle"
import { useLiveEvents } from "@/lib/live"
import { useInfo, useProjects } from "@/lib/queries"
import { sortForSwitcher } from "@/lib/switcher"

/** The header, project switcher, phone picker, agent drawer and the "well" around every route. */
export function AppShell({ children }: { children: ReactNode }) {
  const { data: info } = useInfo()
  const { data: projects } = useProjects()
  const { pathname } = useLocation()
  const [drawer, setDrawer] = useState(false)
  const [sheet, setSheet] = useState(false)
  const [wire, setWire] = useState(false)
  const agentBtn = useRef<HTMLButtonElement>(null)
  useLiveEvents()

  const current = matchPath("/p/:name/*", pathname)?.params.name ?? matchPath("/p/:name", pathname)?.params.name
  const update = info?.update
  // The bell counts what the backend says needs Alex (each project's needs_you); nothing is worked out here.
  const need = (projects ?? []).reduce((n, p) => n + (p.needs_you ?? 0), 0)
  const firstNeed = need ? sortForSwitcher(projects ?? []).find((p) => p.needs_you > 0)?.name : undefined
  const inProjects = pathname === "/" || pathname.startsWith("/p/") || pathname === "/new" || pathname === "/import"

  useEffect(() => {
    setWire(true)
    setSheet(false)
    window.scrollTo?.(0, 0)
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
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [])

  const closeDrawer = () => {
    setDrawer(false)
    agentBtn.current?.focus()
  }

  return (
    <div className="min-h-screen overflow-x-hidden">
      <header className="top gut">
        <Link className="brand" to="/" aria-label="Phoenix, go to projects">
          <span className="mark"><Icon name="flame" /></span>
          <span className="wordmark">
            <b>Phoenix</b>
            {info && <span title="Installed release">{info.label ?? info.version}</span>}
          </span>
        </Link>
        <Link className="navlink" to="/" aria-current={inProjects ? "page" : undefined}>
          <Icon name="squares-four" size="sm" />
          Projects
        </Link>
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
          <Link
            className="hbtn"
            to={firstNeed ? `/p/${encodeURIComponent(firstNeed)}/overview` : "/"}
            aria-label={need ? `Needs you: ${need} ${need === 1 ? "question" : "questions"} waiting` : "Needs you: nothing waiting"}
            title={need ? `${need} ${need === 1 ? "question needs" : "questions need"} you` : "Nothing needs you"}
          >
            <Icon name="bell-ringing" />
            {need > 0 && <span className="cnt" data-testid="bell-count">{need}</span>}
          </Link>
          <button ref={agentBtn} className="hbtn" aria-label="Open Phoenix Agent" title="Phoenix Agent (Ctrl .)" onClick={() => setDrawer(true)}>
            <Icon name="flame" />
            <span className="wtxt">Agent</span>
          </button>
          <ThemeToggle />
          <Link className="hbtn" to="/settings" aria-label="Settings" title="Phoenix settings">
            <Icon name="gear" />
            <span className="wtxt">Settings</span>
          </Link>
        </div>
      </header>

      <div className="shell gut">
        <ProjectSwitcher current={current} />
        <main className={pathname.endsWith("/logs") ? "well console" : "well"}>
          <div className={wire ? "wire on" : "wire"} data-testid="wire" />
          <Crumbs />
          {children}
        </main>
      </div>

      <div className={drawer || sheet ? "scrim open" : "scrim"} data-testid="scrim" onClick={() => { closeDrawer(); setSheet(false) }} />
      <AgentDrawer open={drawer} onClose={closeDrawer} />
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
