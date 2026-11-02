// One build, live: title with Stop build, the stacked blocks, and the sticky summary beside them.
import { useState } from "react"
import { Link } from "react-router"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { ErrorState } from "@/components/ErrorState"
import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { RelativeTime } from "@/components/RelativeTime"
import { Tag } from "@/components/Tag"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { NeedsYouCard } from "@/features/gates/NeedsYouCard"
import { useBuilds, useStopRun } from "@/lib/queries"
import type { RunDetail } from "@/lib/types"

import { edgeOf, Muted, ResultBadge } from "./parts"
import { StepList } from "./StepList"
import { runSummary, useRunLive } from "./useRunLive"

interface Props {
  name: string
  runId: string
  /** How the Build tab hears about changes (from its one useLiveEvents). */
  mode: "live" | "polling"
}

const RING = 2 * Math.PI * 36
const RING_COLOUR = { ok: "var(--ok)", bad: "var(--bad)", need: "var(--attn)", run: "var(--accent)", none: "var(--line-strong)" }

/** The summary line under the ring, in plain words. */
function sumLine(d: RunDetail, total: number, passed: number): string {
  const current = d.current?.step
  switch (d.status) {
    case "done": return `All ${total} tasks done`
    case "waiting": return passed >= total && total > 0 ? `All ${total} tasks done; merge waiting` : "A step is waiting for you"
    case "running": return current ? `The ${current} step is working${d.current?.task ? ` on task ${d.current.task}` : ""}` : "Running"
    case "failed": return "The build failed"
    case "stopped": return "The build was stopped"
    default: return "Waiting for the runner"
  }
}

function Summary({ d, name, cost, started, duration, taskLine, live }: {
  d: RunDetail; name: string; cost: string; started: string; duration: string; taskLine: string; live: string | null
}) {
  const tasks = Object.values(d.tasks)
  const total = tasks.length
  const passed = tasks.filter((t) => t.status === "passed").length
  const edge = edgeOf(d.status)
  const failed = tasks.filter((t) => t.status === "failed").length
  const text = d.status === "running" && taskLine ? `Running ${taskLine.toLowerCase()}` : undefined
  const result = text ?? (d.status === "done" ? "Done" : d.status === "waiting" ? "Waiting for you" : d.status === "failed" ? (failed ? `${failed} of ${total} tasks failed` : "Failed") : d.status === "stopped" ? "Stopped" : "Queued")
  return (
    <aside className="card run-sum" aria-label="Build summary">
      <div className="row" style={{ gap: 16 }}>
        <div className="ring" style={{ ["--ring" as string]: RING_COLOUR[edge] }}>
          <svg viewBox="0 0 84 84" aria-hidden="true">
            <circle className="tr" cx="42" cy="42" r="36" />
            <circle className="vl" cx="42" cy="42" r="36" strokeDasharray={`${total ? RING * (passed / total) : 0} ${RING}`} />
          </svg>
          <b data-testid="ring-text">{passed}/{total}</b>
        </div>
        <div className="stackg" style={{ gap: 6 }}>
          <ResultBadge status={d.status} text={result} />
          <span className="small" data-testid="sum-line">{sumLine(d, total, passed)}</span>
        </div>
      </div>
      <dl className="kv">
        <dt>Preset</dt><dd><Tag>{d.preset}</Tag></dd>
        <dt>Started</dt><dd><RelativeTime iso={started} /></dd>
        <dt>Duration</dt><dd className="mono">{duration}</dd>
        <dt>Cost</dt><dd className="mono">{cost}</dd>
      </dl>
      {live && <span className="live" data-testid="live-mode"><i />{live}</span>}
      <Link to={`/p/${encodeURIComponent(name)}/logs?run=${encodeURIComponent(d.run_id)}`}>See this build's logs</Link>
    </aside>
  )
}

/** The running (or finished) view of one build. */
export function RunningView({ name, runId, mode }: Props) {
  const run = useRunLive(name, runId, mode)
  const builds = useBuilds(name)
  const stop = useStopRun(name)
  const [confirming, setConfirming] = useState(false)

  // A failed background refresh keeps the last good view; the error box is only for "never loaded".
  if (run.error && !run.data) return <ErrorState error={run.error} onRetry={() => void run.refetch()} />
  const d = run.data
  if (!d) return <Skeleton className="h-24 w-full" />

  const s = runSummary(d)
  const row = builds.data?.find((b) => b.run_id === runId)
  const cost = row?.cost || (d.usage.cost_usd != null ? `$${d.usage.cost_usd.toFixed(2)}` : "-")
  const started = row?.started || d.created

  return (
    <div className="stackg min-w-0" style={{ gap: 20 }}>
      <div className="run-head">
        <div className="min-w-0">
          <h2 className="h2 break-words" style={{ fontSize: 30 }}>{d.title || d.run_id}</h2>
          <p className="small">Started <RelativeTime iso={started} /></p>
        </div>
        {s.active && (
          <Button variant="danger" disabled={stop.isPending} onClick={() => setConfirming(true)}>
            {stop.isPending ? <Wheel /> : <Icon name="stop-circle" />}
            Stop build
          </Button>
        )}
      </div>
      {run.error && <p role="status" className="small">Can't reach Phoenix right now; showing the last update.</p>}
      {stop.error && (
        <Alert variant="destructive"><AlertDescription>{stop.error.message}</AlertDescription></Alert>
      )}
      {s.waitingForRunner && <Muted>Queued: waiting for the runner to pick it up.</Muted>}
      {s.gatesAbove.map((g) => <NeedsYouCard key={g.id} gate={g} />)}
      <div className="run">
        <StepList run={d} />
        <Summary
          d={d} name={name} cost={cost} started={started} duration={row?.duration || "-"} taskLine={s.taskLine}
          live={s.active ? (mode === "live" ? "Live" : "Updating every few seconds") : null}
        />
      </div>
      {s.finished && <p className="small" data-testid="result">Result: {s.result}</p>}
      <ConfirmDialog
        open={confirming} onOpenChange={setConfirming} title="Stop this build?"
        body="The build stops now. Work done so far stays on its branch." confirmLabel="Stop build" destructive
        onConfirm={() => stop.mutate(runId)}
      />
    </div>
  )
}
