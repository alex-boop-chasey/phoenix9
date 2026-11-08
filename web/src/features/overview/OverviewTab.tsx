// The Overview tab: open questions, the current build, recent changes, and the About card.
import { Link, useSearchParams } from "react-router"

import { Icon } from "@/components/Icon"
import { StatusBadge } from "@/components/StatusBadge"
import { Tag } from "@/components/Tag"
import { DeployCard } from "@/features/deploy/DeployCard"
import { NeedsYouCard } from "@/features/gates/NeedsYouCard"
import { useBuilds, useChangelog, useGates, useProject } from "@/lib/queries"
import { useLiveEvents } from "@/lib/live"
import { useScrollToId } from "@/lib/focus"
import { findRoute } from "@/lib/routes"
import type { BuildRow, ProjectRow } from "@/lib/types"

import { AboutCard } from "./AboutCard"

/** One bar piece per task (done, failed, the running one), plus an orange piece when the merge is waiting. */
function taskBar(build: BuildRow | undefined, run: NonNullable<ProjectRow["run"]>) {
  const total = build?.tasks_total ?? run.tasks
  const passed = build?.tasks_passed ?? 0
  const failed = build?.tasks_failed ?? 0
  const pieces: string[] = []
  for (let i = 0; i < total; i++) {
    if (i < passed) pieces.push("ok")
    else if (i < passed + failed) pieces.push("bad")
    else if (run.status === "running" && i === passed + failed) pieces.push("run")
    else pieces.push("")
  }
  if (run.status === "waiting" && passed >= total) pieces.push("need")
  return { pieces, total, passed }
}

function CurrentBuild({ name, row, builds, loaded }: { name: string; row: ProjectRow | undefined; builds: BuildRow[]; loaded: boolean }) {
  const run = row?.run ?? null
  const build = run ? builds.find((b) => b.run_id === run.run_id) : undefined
  const waiting = run?.status === "waiting"
  const bar = row && run ? taskBar(build, run) : null
  return (
    <section className="card stackg" aria-labelledby="ov-cb">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 className="h2" id="ov-cb" style={{ fontSize: 22 }}>Current build</h2>
        <Link to={`/p/${encodeURIComponent(name)}/build`}>Open the Build tab</Link>
      </div>
      {row && run && bar ? (
        <>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <b className="h3">{build?.title || run.run_id}</b>
            <StatusBadge status={run.status} />
          </div>
          <div className="tbar" aria-label={`${bar.passed} of ${bar.total} tasks done${waiting ? ", merge waiting" : ""}`}>
            {bar.pieces.map((c, i) => <i key={i} className={c} />)}
          </div>
          <p className="small mono">
            {[`${bar.passed} of ${bar.total} tasks`, build?.cost, build?.duration].filter(Boolean).join(" · ")}
          </p>
          {run.worker === "not responding" && (
            <p role="alert" className="small"><b>Worker not responding.</b> {run.why}</p>
          )}
          <p className="small">{run.now}</p>
        </>
      ) : loaded && builds.length === 0 ? (
        <div className="stackg">
          <p className="small">This project has no builds yet. A build turns your spec into working code, step by step.</p>
          <Link className="btn btn-primary" to={`/p/${encodeURIComponent(name)}/build?new=1`}>
            <Icon name="hammer" />Start the first build
          </Link>
        </div>
      ) : (
        <p className="small">No build running.</p>
      )}
    </section>
  )
}

const GATE_PARAM = findRoute("p/<name>/overview")!.params[0]!   // "gate"
/** Scroll to the gate named in the address (if it is open) and glow it; unknown ids are ignored. */
function useGateFocus(ids: string[]) {
  const [params] = useSearchParams()
  const wanted = params.get(GATE_PARAM)
  useScrollToId(wanted !== null && ids.includes(wanted) ? `gate-${wanted}` : null, true, "gate-focus")
}

/** The Overview tab: open questions, about, current build and recent changes. */
export function OverviewTab({ name }: { name: string }) {
  useLiveEvents(name)
  const project = useProject(name)
  const gates = useGates(name)
  const builds = useBuilds(name)
  const changes = useChangelog(name, 10)
  const row = project.data
  const open = (gates.data ?? []).filter((g) => g.project === name)   // the API lists only open questions
  const recent = [...(changes.data ?? [])].reverse()
  useGateFocus(open.map((g) => g.id))
  const waitingKeys = project.data?.setup?.waiting_for_keys ?? []

  return (
    <div className="ov">
      <div className="ov-main">
        {open.map((g) => (
          <div key={g.id} id={`gate-${g.id}`}>
            <NeedsYouCard gate={g} reviewHref={`/p/${name}/build?run=${g.run}`} />
          </div>
        ))}
        {waitingKeys.length > 0 && (
          <section className="card stackg" aria-label="Waiting for keys">
            <p className="small"><b>Waiting for keys: {waitingKeys.join(", ")}</b></p>
            <p className="small">Phoenix built the site without {waitingKeys.length === 1 ? "it" : "them"}. Save the keys in
              {" "}<Link to={`/p/${encodeURIComponent(name)}/settings`}>Settings</Link>, then start a new build to switch
              {waitingKeys.length === 1 ? " it" : " them"} on.</p>
          </section>
        )}
        <CurrentBuild name={name} row={row} builds={builds.data ?? []} loaded={!!builds.data} />
        <section className="card" aria-labelledby="ov-rc">
          <h2 className="h2" id="ov-rc" style={{ fontSize: 22, marginBottom: 10 }}>Recent changes</h2>
          {recent.length === 0 ? (
            <p className="small">No changes recorded yet.</p>
          ) : (
            <ul className="changes">
              {recent.map((c, i) => (
                <li key={i}>
                  <i aria-hidden />
                  <time>{c.date}</time>
                  <span>{c.who && <><Tag>{c.who}</Tag>{" "}</>}{c.text}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
        <DeployCard name={name} />
      </div>
      {row && <AboutCard project={row} />}
    </div>
  )
}
