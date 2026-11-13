// The Build tab in three modes: the list of builds, the wizard (?new=1), or one build live (?run=<id>).
import { useEffect, useRef, useState } from "react"
import { useLocation, useNavigate, useSearchParams } from "react-router"

import { ErrorState } from "@/components/ErrorState"
import { Icon } from "@/components/Icon"
import { RelativeTime } from "@/components/RelativeTime"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { scrollPageTop } from "@/lib/focus"
import { useLiveEvents } from "@/lib/live"
import { useBuilds } from "@/lib/queries"
import type { BuildRow } from "@/lib/types"
import { ReferenceCard } from "@/features/reference/ReferenceCard"

import { BuildList } from "./BuildList"
import { rowResult } from "./parts"
import { RunningView } from "./RunningView"
import { activeRun } from "./useRunLive"
import { SLIDE_COUNT } from "./wizard/model"
import { Wizard } from "./wizard/Wizard"

type Mode = { kind: "list" } | { kind: "wizard"; slide: number } | { kind: "run"; runId: string }

/** Which mode the address asks for (a bare address is the list, unless a run is active). */
export function modeFrom(params: URLSearchParams): Mode | null {
  const slide = Number(params.get("wizard"))
  if (Number.isInteger(slide) && slide >= 1) return { kind: "wizard", slide: Math.min(slide, SLIDE_COUNT) }
  if (params.get("new") === "1") return { kind: "wizard", slide: 1 }
  const run = params.get("run")
  if (run) return { kind: "run", runId: run }
  if (params.get("list") === "1") return { kind: "list" }
  return null
}

const DRAWER_KEY = "phoenix.build.previousOpen"
const FINISHED = ["done", "failed", "stopped"]

/** Whether the previous-builds drawer was open last time; null when never set or storage is off. */
function readDrawer(): boolean | null {
  try {
    const v = window.localStorage.getItem(DRAWER_KEY)
    return v === null ? null : v === "1"
  } catch {
    return null
  }
}

/** Remember whether the previous-builds drawer is open; does nothing when storage is off. */
function writeDrawer(open: boolean) {
  try {
    window.localStorage.setItem(DRAWER_KEY, open ? "1" : "0")
  } catch {
    /* storage is off: the drawer just is not remembered */
  }
}

/** The newest finished build (passed, failed or stopped), if any. */
export function lastFinished(rows: BuildRow[]): BuildRow | undefined {
  const when = (r: BuildRow) => r.finished || r.started || r.created || ""
  return rows.filter((r) => FINISHED.includes(r.status)).sort((a, b) => when(b).localeCompare(when(a)))[0]
}

/** The folded list of all builds; its closed line says how many and how the last finished one went. */
function PreviousBuilds({ name, rows, selected }: { name: string; rows: BuildRow[]; selected?: string }) {
  const [chosen, setChosen] = useState<boolean | null>(readDrawer)
  // With nothing shown above, the drawer starts open so the page is never empty.
  const open = selected ? (chosen ?? false) : (chosen ?? true)
  const last = lastFinished(rows)
  return (
    <details
      className="prev-builds" open={open}
      onToggle={(e) => {
        const now = e.currentTarget.open
        if (now !== open) {
          setChosen(now)
          writeDrawer(now)
        }
      }}
    >
      <summary data-testid="previous-summary">
        <Icon name="caret-right" size="sm" className="car" />
        <span className="h2 prev-h" id="b-list">Previous builds ({rows.length})</span>
        {last && (
          <span className="small">
            {" · "}last: {rowResult(last)}, <RelativeTime iso={last.finished || last.started || last.created} />
          </span>
        )}
      </summary>
      <div className="prev-in">
        <BuildList name={name} rows={rows} selected={selected} />
      </div>
    </details>
  )
}

/** The Build tab. A project with a queued, running or waiting build opens on that build. */
export function BuildTab({ name }: { name: string }) {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const justStarted = (useLocation().state as { started?: boolean } | null)?.started === true
  const onBuildTab = useLocation().pathname.endsWith("/build")
  const builds = useBuilds(name)
  const live = useLiveEvents(name)
  const base = `/p/${encodeURIComponent(name)}/build`
  const asked = modeFrom(params)
  const active = builds.data ? activeRun(builds.data) : undefined

  useEffect(() => {
    // Only while the address is this tab: a closing tab must not pull the page back here.
    if (onBuildTab && !asked && active) void navigate(`${base}?run=${encodeURIComponent(active.run_id)}`, { replace: true })
  }, [onBuildTab, asked, active, base, navigate])

  const selectedRun = asked?.kind === "run" ? asked.runId : undefined
  useEffect(() => {
    // A build that was just started shows from its top.
    if (justStarted && selectedRun) scrollPageTop()
  }, [justStarted, selectedRun])

  const shownRun = useRef(selectedRun)
  useEffect(() => {
    // Choosing another build from the list shows it from its top (it sits above the list).
    if (selectedRun && shownRun.current !== selectedRun) scrollPageTop()
    shownRun.current = selectedRun
  }, [selectedRun])

  if (asked?.kind === "wizard") {
    return (
      <Wizard
        name={name} startSlide={asked.slide} onCancel={() => void navigate(`${base}?list=1`)}
        onStarted={(id) => {
          scrollPageTop()
          void navigate(`${base}?run=${encodeURIComponent(id)}`, { replace: true, state: { started: true } })
        }}
      />
    )
  }
  const selected = asked?.kind === "run" ? asked.runId : undefined
  const startNew = (
    <Button variant="secondary" size="sm" onClick={() => void navigate(`${base}?new=1`)}>
      <Icon name="hammer" />Start new build
    </Button>
  )

  return (
    <section className="build-tab" data-project={name}>
      {selected && (
        <div style={{ marginBottom: 24 }}>
          <RunningView key={selected} name={name} runId={selected} mode={live.mode} />
        </div>
      )}
      <div className="stackg" style={{ gap: 12 }}>
        <div className="row" style={{ justifyContent: "flex-end" }}>{startNew}</div>
        {builds.error ? (
          <ErrorState error={builds.error} onRetry={() => void builds.refetch()} />
        ) : builds.data && !(!asked && active) ? (
          <PreviousBuilds name={name} rows={builds.data} selected={selected} />
        ) : (
          <Skeleton className="h-24 w-full" />
        )}
      </div>
      <div className="stackg" style={{ gap: 12, marginTop: 16 }}>
        <h2 className="h2" id="b-reference">Reference material</h2>
        <ReferenceCard project={name} />
      </div>
    </section>
  )
}
