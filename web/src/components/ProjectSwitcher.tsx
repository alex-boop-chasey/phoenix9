import { Link } from "react-router"

import { ChatButton } from "@/components/ChatButton"
import { Icon } from "@/components/Icon"
import { Indicator, type IndicatorKind } from "@/components/Indicator"
import { useProjects } from "@/lib/queries"
import { sortForSwitcher, switchLine, switchState, type SwitchState } from "@/lib/switcher"
import type { ProjectRow } from "@/lib/types"
import { cn } from "@/lib/utils"

const IND: Record<SwitchState, IndicatorKind> = { need: "needs-you", run: "running", fail: "failed", idle: "pending" }

/** The list of projects (status dot, name, one line), the current one marked with the blue bar. */
export function ProjectList({ rows, current, onPick, withChat }: { rows: ProjectRow[]; current?: string; onPick?: () => void; withChat?: boolean }) {
  return (
    <div>
      {sortForSwitcher(rows).map((p) => (
        <div key={p.name} className="sw-line">
        <Link
          to={`/p/${encodeURIComponent(p.name)}/overview`}
          className={cn("sw-item", switchState(p) === "need" && "is-need")}
          aria-current={p.name === current ? "true" : "false"}
          onClick={onPick}
        >
          <Indicator kind={IND[switchState(p)]} small />
          <b>{p.name}</b>
          <small>{switchLine(p)}</small>
        </Link>
        {withChat && p.name === current && <ChatButton project={p.name} chat={p.chat ?? null} />}
        </div>
      ))}
    </div>
  )
}

/** The desktop project switcher on the left. */
export function ProjectSwitcher({ current }: { current?: string }) {
  const { data } = useProjects()
  return (
    <nav className="switcher" aria-label="Project switcher">
      <div className="sw-head">
        <span>Projects</span>
        <Link to="/">See all</Link>
      </div>
      <ProjectList rows={data ?? []} current={current} withChat />
      <div className="sw-sep" />
      <Link className="btn btn-ghost btn-sm sw-add" to="/new">
        <Icon name="plus" />
        New project
      </Link>
      <Link className="btn btn-ghost btn-sm" to="/styles">
        <Icon name="palette" />
        Style reference
      </Link>
    </nav>
  )
}
