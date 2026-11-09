import { Link } from "react-router"

import { ChatButton } from "@/components/ChatButton"
import { Icon } from "@/components/Icon"
import { Indicator, type IndicatorKind } from "@/components/Indicator"
import { useProjects } from "@/lib/queries"
import { agentStalled, agentTitle, groupForSwitcher, groupOf, switchLine, switchState, type SwitchState } from "@/lib/switcher"
import type { ProjectRow } from "@/lib/types"
import { cn } from "@/lib/utils"

const IND: Record<SwitchState, IndicatorKind> = { need: "needs-you", run: "running", fail: "failed", idle: "pending" }

/** The list of projects (status dot, name, one line), the current one marked with the blue bar. */
export function ProjectList({ rows, current, onPick, withChat }: { rows: ProjectRow[]; current?: string; onPick?: () => void; withChat?: boolean }) {
  return (
    <div>
      {groupForSwitcher(rows).map((g, i) => (
        <section key={g.key} aria-label={g.title}>
          {i > 0 && <div className="sw-sep" role="separator" />}
          <h3 className="eyebrow sw-group">{g.title}</h3>
          {g.rows.map((p) => (
            <Row key={p.name} p={p} current={current} onPick={onPick} withChat={withChat} />
          ))}
        </section>
      ))}
    </div>
  )
}

function Row({ p, current, onPick, withChat }: { p: ProjectRow; current?: string; onPick?: () => void; withChat?: boolean }) {
  const agent = groupOf(p) === "agent"
  const line = agent ? agentTitle(p) : switchLine(p)
  return (
    <div className="sw-line">
      <Link
        to={`/p/${encodeURIComponent(p.name)}/overview`}
        className={cn("sw-item", switchState(p) === "need" && "is-need")}
        aria-current={p.name === current ? "true" : "false"}
        onClick={onPick}
      >
        <Indicator kind={agent ? (agentStalled(p) ? "off" : "running") : IND[switchState(p)]} small />
        <b>{p.name}</b>
        <small>{line}</small>
      </Link>
      {withChat && p.name === current && <ChatButton project={p.name} chat={p.chat ?? null} compact />}
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
