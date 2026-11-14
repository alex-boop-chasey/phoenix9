// One build, live: title with Stop build, the stacked blocks, and the sticky summary beside them.
import { RunDocs } from "@/features/docs/RunDocs"
import { useEffect, useState } from "react"
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
import { unlockUsedText } from "@/features/gates/repairUnlock"
import { useBuilds, usePauseRun, useResumeRun, useRunEstimates, useStopRun } from "@/lib/queries"
import type { RunDetail, RunEstimates } from "@/lib/types"

import { DiscardControl } from "./DiscardControl"
import { badgeResult, edgeOf, ResultBadge } from "./parts"
import { currentLine, buildLeft, stepProgress, toGo } from "./progress"
import { liveClock, StepList, StepListLead } from "./StepList"
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
  if (d.carrying_on) return "Answered: Phoenix is carrying on"
  switch (d.status) {
    case "done": return `All ${total} tasks done`
    case "waiting": return passed >= total && total > 0 ? `All ${total} tasks done; merge waiting` : "A step is waiting for you"
    case "running": return current ? `The ${current} step is working${d.current?.task ? ` on task ${d.current.task}` : ""}` : "Running"
    case "failed": return "The build failed"
    case "paused": return "The build is paused; Resume carries on from the same step"
    case "stopped": return "The build was stopped"
    default: return "Starting: the first step runs in a moment"
  }
}

/** The ring's fill when no step is being timed: full when done, else the share of tasks passed. */
function restingFill(d: RunDetail, total: number, passed: number): number {
  if (d.status === "done") return 1
  return total ? passed / total : 0
}

function Summary({ d, name, cost, started, duration, taskLine, live, estimates, now }: {
  d: RunDetail; name: string; cost: string; started: string; duration: string; taskLine: string; live: string | null
  estimates: RunEstimates | undefined; now: number
}) {
  const tasks = Object.values(d.tasks)
  const total = tasks.length
  const passed = tasks.filter((t) => t.status === "passed").length
  const edge = edgeOf(d.status)
  const failed = tasks.filter((t) => t.status === "failed").length
  const text = d.status === "running" && taskLine ? `Running ${taskLine.toLowerCase()}` : undefined
  const result = text ?? (d.status === "done" ? "Done" : d.status === "waiting" ? "Waiting for you" : d.status === "paused" ? "Paused" : d.status === "failed" ? (failed ? `${failed} of ${total} tasks failed` : d.failed_at?.text || "Failed") : d.status === "stopped" ? "Stopped" : "Starting…")
  const badge = badgeResult(d.status, failed, result, d.failed_at)
  // The ring follows the step the build is on now; with no history for it, it just turns calmly (O41).
  const moving = d.status === "running" || d.status === "queued"
  const step = moving ? stepProgress(d, estimates, now) : { fill: restingFill(d, total, passed), line: "" }
  const left = d.status === "running" ? buildLeft(d, estimates, now) : null
  const current = d.status === "running" || d.status === "waiting" ? currentLine(d) : undefined
  return (
    <aside className="card run-sum" aria-label="Build summary">
      <div className="row" style={{ gap: 16 }}>
        <div
          className={`sum-ring${step.fill === null ? " calm" : ""}`} data-testid="sum-ring"
          data-fill={step.fill === null ? "calm" : step.fill.toFixed(3)}
          style={{ ["--ring-colour" as string]: RING_COLOUR[edge] }}
        >
          <svg viewBox="0 0 84 84" aria-hidden="true">
            <circle className="tr" cx="42" cy="42" r="36" />
            <circle className="vl" cx="42" cy="42" r="36" strokeDasharray={`${RING * (step.fill ?? 0.25)} ${RING}`} />
          </svg>
        </div>
        <div className="stackg" style={{ gap: 6 }}>
          <ResultBadge status={d.status} {...badge} />
          <span className="small" data-testid="sum-line">{sumLine(d, total, passed)}</span>
          {step.line && <span className="small" data-testid="step-to-go">{step.line}</span>}
          {left !== null && left > 0 && <span className="small" data-testid="build-to-go">Whole build: {toGo(left)}</span>}
        </div>
      </div>
      {total > 0 && <p className="small" data-testid="task-count">Tasks {passed} of {total} done</p>}
      <dl className="kv">
        <dt>Preset</dt><dd><Tag>{d.preset}</Tag></dd>
        <dt>Started</dt><dd><RelativeTime iso={started} /></dd>
        <dt>Build running</dt><dd className="mono">{duration}</dd>
        {current && <><dt>This step</dt><dd data-testid="this-step">{liveClock(current)}</dd></>}
        <dt>Cost</dt><dd className="mono">{cost}</dd>
      </dl>
      {live && <span className="live" data-testid="live-mode"><i />{live}</span>}
      <RunDocs runId={d.run_id} />
      <Link to={`/p/${encodeURIComponent(name)}/logs?run=${encodeURIComponent(d.run_id)}`}>See this build's logs</Link>
    </aside>
  )
}

/** Re-render every few seconds while on, so the clocks and the ring keep moving. */
function useTick(on: boolean, ms = 2000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!on) return
    const id = window.setInterval(() => setNow(Date.now()), ms)
    return () => window.clearInterval(id)
  }, [on, ms])
  return now
}

/** The running (or finished) view of one build. */
export function RunningView({ name, runId, mode }: Props) {
  const run = useRunLive(name, runId, mode)
  const builds = useBuilds(name)
  const stop = useStopRun(name)
  const pause = usePauseRun(name)
  const resume = useResumeRun(name)
  const [confirming, setConfirming] = useState(false)
  const [pausing, setPausing] = useState(false)
  const going = run.data?.status === "running" || run.data?.status === "queued"
  const estimates = useRunEstimates(name, going)
  const now = useTick(going || run.data?.status === "waiting")

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
          <p className="small">
            Started <RelativeTime iso={started} />
            {d.budget_usd ? <> · <span data-testid="budget">${(d.spent_usd ?? d.usage.cost_usd ?? 0).toFixed(2)} of ${d.budget_usd.toFixed(2)}</span></> : null}
            {d.branch && <> · branch <span className="mono">{d.branch}</span></>}
            {d.image?.id && <> · image <span className="mono" title={`${d.image.tag} ${d.image.id}`} data-testid="image-id">{d.image.id.replace(/^sha256:/, "").slice(0, 12)}</span></>}
          </p>
        </div>
        {!s.active && <DiscardControl name={name} run={d} />}
        {s.active && (
          <div className="row" style={{ gap: 8 }}>
            {d.status === "paused" ? (
              <Button variant="secondary" disabled={resume.isPending} onClick={() => resume.mutate(runId)}>
                {resume.isPending ? <Wheel /> : <Icon name="play-circle" />}
                Resume
              </Button>
            ) : (
              <>
                <Button variant="secondary" disabled={pause.isPending} onClick={() => setPausing(true)}>
                  {pause.isPending ? <Wheel /> : <Icon name="pause-circle" />}
                  Pause now
                </Button>
                <Button variant="danger" disabled={stop.isPending} onClick={() => setConfirming(true)}>
                  <Icon name="stop-circle" />
                  Stop build
                </Button>
              </>
            )}
            {d.status === "paused" && (
              <Button variant="danger" disabled={stop.isPending} onClick={() => setConfirming(true)}>
                {stop.isPending ? <Wheel /> : <Icon name="stop-circle" />}
                Stop
              </Button>
            )}
          </div>
        )}
      </div>
      {run.error && <p role="status" className="small">Can't reach Phoenix right now; showing the last update.</p>}
      {stop.data?.status === "stop requested" && (
        <p role="status" className="small">Stop requested: Phoenix stops this build at the end of the step it is on.</p>
      )}
      {pause.data?.waits_for_step && (
        <p role="status" className="small">Pause requested: Phoenix pauses this build when the step it is on ends.</p>
      )}
      {(pause.error || resume.error) && (
        <Alert variant="destructive"><AlertDescription>{(pause.error ?? resume.error)?.message}</AlertDescription></Alert>
      )}
      {stop.error && (
        <Alert variant="destructive"><AlertDescription>{stop.error.message}</AlertDescription></Alert>
      )}
      {s.waitingForRunner && (
        <p className="row small" role="status" data-testid="starting"><Wheel />Starting… the first step runs in a moment.</p>
      )}
      {s.gatesAbove.map((g) => <NeedsYouCard key={g.id} gate={g} run={d} />)}
      <div className="run">
        {/* The lead sits above both columns' second row, so the card's top lines up with the first step (O42). */}
        <div className="stack run-lead"><StepListLead run={d} /></div>
        <div className="run-steps"><StepList run={d} lead={false} /></div>
        <Summary
          d={d} name={name} cost={cost} started={started} duration={row?.duration || "-"} taskLine={s.taskLine}
          live={s.active ? (mode === "live" ? "Live" : "Updating every few seconds") : null}
          estimates={estimates.data} now={now}
        />
      </div>
      {s.finished && <p className="small" data-testid="result">Result: {s.result}</p>}
      {(d.unlocks_used ?? []).map((u, i) => (
        <p key={`${u.at}-${i}`} className="small" data-testid="unlock-used">{unlockUsedText(u)}</p>
      ))}
      <ConfirmDialog
        open={pausing} onOpenChange={setPausing} title="Pause now?"
        body="Stop the build at once? The work so far is kept and it carries on from the same step when you resume."
        confirmLabel="Pause now" onConfirm={() => pause.mutate(runId)}
      />
      <ConfirmDialog
        open={confirming} onOpenChange={setConfirming} title="Stop this build?"
        body="The build stops, and its unfinished work and branch are thrown away." confirmLabel="Stop build" destructive
        onConfirm={() => stop.mutate(runId)}
      />
    </div>
  )
}
