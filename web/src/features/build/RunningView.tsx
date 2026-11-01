// One build, live: header with Stop, open questions, the step list, and the result once it finishes.
import { Loader2 } from "lucide-react"
import { useState } from "react"
import { Link } from "react-router"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { ErrorState } from "@/components/ErrorState"
import { RelativeTime } from "@/components/RelativeTime"
import { StatusBadge } from "@/components/StatusBadge"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { NeedsYouCard } from "@/features/gates/NeedsYouCard"
import { useBuilds, useStopRun } from "@/lib/queries"

import { Muted } from "./parts"
import { StepList } from "./StepList"
import { runSummary, useRunLive } from "./useRunLive"

interface Props {
  name: string
  runId: string
  /** How the Build tab hears about changes (from its one useLiveEvents). */
  mode: "live" | "polling"
}

/** The running (or finished) view of one build. */
export function RunningView({ name, runId, mode }: Props) {
  const run = useRunLive(name, runId, mode)
  const builds = useBuilds(name)
  const stop = useStopRun(name)
  const [confirming, setConfirming] = useState(false)
  const base = `/p/${encodeURIComponent(name)}`
  const allBuilds = <Link to={`${base}/build?list=1`} className="text-sm text-primary hover:underline">← All builds</Link>
  const logs = (
    <Link to={`${base}/logs?run=${encodeURIComponent(runId)}`} className="text-primary hover:underline">
      See this build's logs
    </Link>
  )

  if (run.error) return <div className="flex flex-col gap-3">{allBuilds}<ErrorState error={run.error} onRetry={() => void run.refetch()} /></div>
  const d = run.data
  if (!d) return <div className="flex flex-col gap-3">{allBuilds}<Skeleton className="h-24 w-full" /></div>

  const s = runSummary(d)
  const row = builds.data?.find((b) => b.run_id === runId)
  const cost = row?.cost || (d.usage.cost_usd != null ? `$${d.usage.cost_usd.toFixed(2)}` : "-")

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {allBuilds}
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <h2 className="min-w-0 break-words text-xl font-semibold">{d.title || d.run_id}</h2>
          {s.active && (
            <Button variant="destructive" size="sm" disabled={stop.isPending} onClick={() => setConfirming(true)}>
              {stop.isPending && <Loader2 className="animate-spin" aria-hidden />}
              Stop
            </Button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
          <span>Preset: {d.preset}</span>
          <span className="inline-flex items-center gap-2" data-testid="run-status">
            <StatusBadge status={d.status} />
            {s.taskLine && <span>{s.taskLine}</span>}
          </span>
          <span>Started: <RelativeTime iso={row?.started || d.created} /></span>
          <span>Duration: {row?.duration || "-"}</span>
          <span>Cost: {cost}</span>
          {s.active && (
            <span className="text-xs text-muted-foreground" data-testid="live-mode">
              {mode === "live" ? "Live" : "Updating every few seconds"}
            </span>
          )}
        </div>
      </header>
      {stop.error && (
        <Alert variant="destructive"><AlertDescription>{stop.error.message}</AlertDescription></Alert>
      )}
      {s.waitingForRunner && <Muted>Queued: waiting for the runner to pick it up.</Muted>}
      {s.gatesAbove.map((g) => <NeedsYouCard key={g.id} gate={g} />)}
      <StepList run={d} />
      {s.finished ? (
        <section className="flex flex-col gap-3 rounded-lg border p-4" aria-label="Result">
          <p className="font-medium">Result: {s.result}</p>
          {logs}
          <Button asChild variant="outline" className="self-start">
            <Link to={`${base}/build?list=1`}>Back to builds</Link>
          </Button>
        </section>
      ) : (
        logs
      )}
      <ConfirmDialog
        open={confirming} onOpenChange={setConfirming} title="Stop this build?"
        body="The build stops now. Work done so far stays on its branch." confirmLabel="Stop build" destructive
        onConfirm={() => stop.mutate(runId)}
      />
    </div>
  )
}
