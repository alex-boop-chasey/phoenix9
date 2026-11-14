// How many tries a task took ("Passed on try 3 of 5"); tapping it lists each try with its result and reason.
import type { MouseEvent } from "react"

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import type { RunDetail, RunTask, TryLine } from "@/lib/types"

/** The plain words for a task's tries, or "" when it has not been tried yet. */
export function triesText(task: RunTask, maxTries: number | null | undefined): string {
  const n = task.tries
  const of = maxTries ? ` of ${maxTries}` : ""
  if (task.status === "passed") return n <= 1 ? "Passed first try" : `Passed on try ${n}${of}`
  if (task.status === "failed") return `Failed after ${n} ${n === 1 ? "try" : "tries"}`
  if (n <= 0) return ""
  return `Try ${n}${of}`
}

const RESULT: Record<string, string> = { passed: "passed", failed: "failed", running: "still going", skipped: "skipped" }

/** One try in plain words: "Try 2: failed at Check · tests did not pass". */
export function tryLineText(t: TryLine, stepTitle: (step: string) => string): string {
  const result = RESULT[t.status] ?? t.status
  const where = t.status === "failed" && t.step ? ` at ${stepTitle(t.step)}` : ""
  return `Try ${t.attempt}: ${result}${where}${t.reason ? ` · ${t.reason}` : ""}`
}

/** Keep a tap on the tries text inside it (a button in a summary does not toggle the block; this stops parents' click handlers). */
const keepInside = (e: MouseEvent) => e.stopPropagation()

/** A task's tries text; a click or tap opens a small list with one line per try. */
export function TaskTries({ run, n, stepTitle }: { run: RunDetail; n: number; stepTitle: (step: string) => string }) {
  const task = run.tasks[String(n)]
  if (!task) return null
  const text = triesText(task, run.max_tries)
  if (!text) return null
  const lines = run.try_lines?.[String(n)] ?? []
  if (lines.length === 0) return <span className="tries-text small" data-tries={n}>{text}</span>
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button" className="tries-btn small" data-tries={n} aria-label={`${text}: show each try`}
          onClick={keepInside}
        >
          {text}
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 p-3" onClick={keepInside}>
        <p className="small" style={{ fontWeight: 600, marginBottom: 6 }}>Task {n} tries</p>
        <ol className="tries-list">
          {lines.map((t) => (
            <li key={t.attempt} className={`small try-${t.status}`}>{tryLineText(t, stepTitle)}</li>
          ))}
        </ol>
      </PopoverContent>
    </Popover>
  )
}
