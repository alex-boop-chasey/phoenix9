import type { Gate, GateReview, RunDetail } from "@/lib/types"

const DELEGATED_FLAG = "handed to the Phoenix agent"   // the backend flag (failmodes.HANDOFF_FLAG); only says who answers

/** "full suite did not pass" -> "Full suite did not pass". */
const sentence = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)

/** A finish step's name in words; the full suite is "Final test run". */
function stepWords(run: RunDetail, step: string): string {
  if (step === "full-suite") return "Final test run"
  const title = (run.plan.steps ?? []).find((r) => r.name === step)?.title
  return title || sentence(step.replace(/-/g, " "))
}

/** What failed or was skipped in the run itself: tasks, then the latest try of each finish step. */
function runProblems(run: RunDetail): string[] {
  const out: string[] = []
  const numbers = Object.keys(run.tasks).map(Number).sort((a, b) => a - b)
  for (const n of numbers) {
    const status = run.tasks[String(n)]!.status
    if (status === "failed") out.push(`Task ${n} failed`)
    else if (status === "skipped") out.push(`Task ${n} was skipped`)
  }
  const latest = new Map<string, string>()
  for (const line of run.steps) {
    if (line.task === null && line.step !== "merge") latest.set(line.step, line.status)
  }
  for (const [step, status] of latest) {
    if (status === "failed") out.push(`${stepWords(run, step)} failed`)
    else if (status === "skipped") out.push(`${stepWords(run, step)} was skipped`)
  }
  return out
}

/** What the merge review says went wrong: tasks that did not pass and a failed or skipped full suite. */
function reviewProblems(review: GateReview): string[] {
  const out: string[] = []
  const notPassed = review.tasks.total - review.tasks.passed
  if (notPassed > 0) out.push(`${notPassed} of ${review.tasks.total} tasks did not pass`)
  if (review.full_suite.status === "failed") out.push("Final test run failed")
  else if (review.full_suite.status === "skipped") out.push("Final test run was skipped")
  return out
}

/** Everything Alex should hear before merging, in plain words; empty for a clean run. */
export function mergeWarnings({ gate, review, run }: { gate: Gate; review?: GateReview; run?: RunDetail }): string[] {
  const found = run ? runProblems(run) : review ? reviewProblems(review) : []
  if (run && review && found.length === 0) found.push(...reviewProblems(review))
  for (const f of gate.flags) if (f !== DELEGATED_FLAG) found.push(sentence(f))
  return [...new Set(found)]
}
