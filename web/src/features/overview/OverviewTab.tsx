// The Overview tab: open questions, the current build, recent changes, and the About card.
import { Link } from "react-router"

import { StatusBadge } from "@/components/StatusBadge"
import { Tag } from "@/components/Tag"
import { DeployCard } from "@/features/deploy/DeployCard"
import { NeedsYouCard } from "@/features/gates/NeedsYouCard"
import { useBuilds, useChangelog, useGates, useProject } from "@/lib/queries"
import { useLiveEvents } from "@/lib/live"
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

function nowLine(row: ProjectRow, build: BuildRow | undefined, waiting: boolean): string {
  if (waiting && build?.current?.step) return `Now: the ${build.current.step} step is waiting for you.`
  if (waiting) return "Now: waiting for you."
  const run = row.run
  if (run?.status === "running") return run.task != null ? `Now: working on task ${run.task} of ${run.tasks}.` : "Now: running."
  return `Now: ${run?.status ?? "idle"}.`
}

function CurrentBuild({ name, row, builds }: { name: string; row: ProjectRow | undefined; builds: BuildRow[] }) {
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
          <p className="small">{nowLine(row, build, waiting)}</p>
        </>
      ) : (
        <p className="small">No build running.</p>
      )}
    </section>
  )
}

/** The Overview tab: open questions, about, current build and recent changes. */
export function OverviewTab({ name }: { name: string }) {
  useLiveEvents(name)
  const project = useProject(name)
  const gates = useGates(name)
  const builds = useBuilds(name)
  const changes = useChangelog(name, 10)
  const row = project.data
  const open = (gates.data ?? []).filter((g) => g.project === name && !g.answered)
  const recent = [...(changes.data ?? [])].reverse()

  return (
    <div className="ov">
      <div className="ov-main">
        {open.map((g) => <NeedsYouCard key={g.id} gate={g} reviewHref={`/p/${name}/build?run=${g.run}`} />)}
        <CurrentBuild name={name} row={row} builds={builds.data ?? []} />
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
