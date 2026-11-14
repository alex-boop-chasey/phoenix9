// One run, kept fresh: events refetch it (via useLiveEvents); when the stream is down it is polled every 4 s.
import { useQuery } from "@tanstack/react-query"

import { api } from "@/lib/api"
import { POLL_MS } from "@/lib/live"
import { keys } from "@/lib/queries"
import type { RunDetail, RunStatus } from "@/lib/types"

import { gatesShownInSteps } from "./StepList"
import { resultText } from "./parts"

const ACTIVE: RunStatus[] = ["queued", "running", "waiting", "paused"]
const FINISHED: RunStatus[] = ["done", "failed", "stopped"]

/** Whether a run can still change (and be stopped). */
export const isActive = (status: RunStatus | undefined) => !!status && ACTIVE.includes(status)

/** Whether a run is over. */
export const isFinished = (status: RunStatus | undefined) => !!status && FINISHED.includes(status)

/** The newest queued, running or waiting run among build rows, if any. */
export function activeRun<T extends { run_id: string; status: RunStatus; created: string; started?: string }>(rows: T[]) {
  const live = rows.filter((r) => isActive(r.status))
  return live.sort((a, b) => (b.started || b.created).localeCompare(a.started || a.created))[0]
}

/** Everything the running view shows about a run, worked out once from its detail. */
export function runSummary(run: RunDetail) {
  const tasks = Object.values(run.tasks)
  const failed = tasks.filter((t) => t.status === "failed").length
  const current = run.current?.task ?? null
  const inSteps = gatesShownInSteps(run)
  return {
    active: isActive(run.status),
    finished: isFinished(run.status),
    result: resultText(run.status, tasks.length, failed, current, run.failed_at),
    taskLine: tasks.length && current ? `Task ${current} of ${tasks.length}` : "",
    waitingForRunner: run.status === "queued" && run.steps.length === 0,
    gatesAbove: run.gates.filter((g) => !g.answered && !inSteps.has(g.id)),
  }
}

/** The run's detail; polled every 4 s only while the event stream is down and the run is not finished. */
export function useRunLive(project: string, runId: string, mode: "live" | "polling") {
  return useQuery({
    queryKey: keys.run(project, runId),
    queryFn: () => api.run(project, runId),
    enabled: !!project && !!runId,
    refetchInterval: (q) => (mode === "polling" && !isFinished(q.state.data?.status) ? POLL_MS : false),
  })
}
