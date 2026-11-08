// Body of the run card: the Build tab's step list for one run.
import { RunDocs } from "@/features/docs/RunDocs"
import { StepList } from "@/features/build/StepList"
import type { RunDetail } from "@/lib/types"

import type { CardBodyProps } from "../cardBodies"

/** The step list of a run card. */
export function RunBody({ data }: CardBodyProps) {
  const run = data as RunDetail | null
  if (!run || !run.plan || !run.tasks || !run.steps) return <p className="muted">This build has no steps to show.</p>
  return <div data-testid="card-run"><StepList run={run} /><RunDocs runId={run.run_id} /></div>
}
