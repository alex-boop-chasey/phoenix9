// The Build tab in three modes: the list of builds, the wizard (?new=1), or one build live (?run=<id>).
import { useEffect } from "react"
import { useLocation, useNavigate, useSearchParams } from "react-router"

import { ErrorState } from "@/components/ErrorState"
import { Icon } from "@/components/Icon"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { useLiveEvents } from "@/lib/live"
import { useBuilds } from "@/lib/queries"

import { BuildList } from "./BuildList"
import { RunningView } from "./RunningView"
import { activeRun } from "./useRunLive"
import { Wizard } from "./wizard/Wizard"

type Mode = { kind: "list" } | { kind: "wizard" } | { kind: "run"; runId: string }

/** Which mode the address asks for (a bare address is the list, unless a run is active). */
export function modeFrom(params: URLSearchParams): Mode | null {
  if (params.get("new") === "1") return { kind: "wizard" }
  const run = params.get("run")
  if (run) return { kind: "run", runId: run }
  if (params.get("list") === "1") return { kind: "list" }
  return null
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
    if (justStarted && selectedRun) window.scrollTo?.(0, 0)
  }, [justStarted, selectedRun])

  if (asked?.kind === "wizard") {
    return (
      <Wizard
        name={name} onCancel={() => void navigate(`${base}?list=1`)}
        onStarted={(id) => {
          window.scrollTo?.(0, 0)
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
      <div className="stackg" style={{ gap: 12 }}>
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 className="h2" id="b-list">Builds</h2>
          {startNew}
        </div>
        {builds.error ? (
          <ErrorState error={builds.error} onRetry={() => void builds.refetch()} />
        ) : builds.data && !(!asked && active) ? (
          <BuildList name={name} rows={builds.data} selected={selected} />
        ) : (
          <Skeleton className="h-24 w-full" />
        )}
      </div>
      {selected && <RunningView key={selected} name={name} runId={selected} mode={live.mode} />}
    </section>
  )
}
