import type { ReactNode } from "react"

import { StatusBadge } from "@/components/StatusBadge"
import { NeedsYouCard } from "@/features/gates/NeedsYouCard"
import { formatDuration, relativeTime } from "@/lib/format"
import type { Gate, ItemStatus, PlanStep, RunDetail, RunTask, StepGroup, StepLine } from "@/lib/types"

import { Muted, ShortText } from "./parts"

/** The latest attempt's line for a step (of one task, or of the run when task is null). */
function latestLine(run: RunDetail, task: number | null, step: string): StepLine | undefined {
  let best: StepLine | undefined
  for (const l of run.steps) {
    if (l.step !== step || (l.task ?? null) !== task) continue
    if (!best || (l.attempt ?? 0) >= (best.attempt ?? 0)) best = l
  }
  return best
}

/** Step names of a group in plan order, including steps switched off. */
function groupNames(run: RunDetail, group: StepGroup): string[] {
  const rows = run.plan.steps ?? []
  const names = [...(run.plan.groups?.[group] ?? [])]
  for (const r of rows) if (r.group === group && !names.includes(r.name)) names.push(r.name)
  const order = (n: string) => rows.find((r) => r.name === n)?.order ?? Number.MAX_SAFE_INTEGER
  return names.sort((a, b) => order(a) - order(b))
}

function planRow(run: RunDetail, name: string): PlanStep | undefined {
  return (run.plan.steps ?? []).find((r) => r.name === name)
}

function openGate(gates: Gate[], id: string | null | undefined): Gate | undefined {
  return id ? gates.find((g) => g.id === id && !g.answered) : undefined
}

/** Where a task's open gate shows: the id of the gate for the task's first failed step, if any. */
function gateFor(run: RunDetail, gates: Gate[], task: number | null, line: StepLine | undefined): Gate | undefined {
  if (!line || line.status !== "failed") return undefined
  const t = task === null ? undefined : run.tasks[String(task)]
  return openGate(gates, line.gate) ?? openGate(gates, t?.gate)
}

/** Ids of the open gates the step list shows itself (so a page can show only the others). */
export function gatesShownInSteps(run: RunDetail, gates: Gate[] = run.gates): Set<string> {
  const ids = new Set<string>()
  for (const n of Object.keys(run.tasks)) {
    const seen = new Set<string>()
    for (const name of groupNames(run, "task")) {
      const g = gateFor(run, gates, Number(n), latestLine(run, Number(n), name))
      if (g && !seen.has(g.id)) {
        seen.add(g.id)
        ids.add(g.id)
      }
    }
  }
  return ids
}

function took(line: StepLine): string {
  const secs = (Date.parse(line.finished) - Date.parse(line.started)) / 1000
  return Number.isFinite(secs) ? `Took ${formatDuration(secs)}` : ""
}

interface Shown {
  status: ItemStatus
  text: string
}

function describe(line: StepLine | undefined, off: PlanStep | undefined, task: RunTask | undefined): Shown {
  if (off && !off.on && !line) return { status: "skipped", text: `Switched off (${off.reason || "switched off"})` }
  if (!line) {
    if (task?.status === "skipped") return { status: "skipped", text: task.note || "skipped" }
    return { status: "pending", text: "" }
  }
  const note = line.note?.split("\n")[0] ?? ""
  if (note) return { status: line.status, text: note }
  switch (line.status) {
    case "running":
      return { status: "running", text: line.started ? `Started ${relativeTime(line.started)}` : "Running" }
    case "waiting":
      return { status: "waiting", text: "Waiting for you" }
    case "passed":
      return { status: "passed", text: took(line) }
    case "skipped":
      return { status: "skipped", text: task?.note || "skipped" }
    default:
      return { status: line.status, text: "" }
  }
}

function StepRow({ title, shown }: { title: string; shown: Shown }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <div className="min-w-0">
        <div className="text-sm font-medium">{title}</div>
        {shown.text && <ShortText text={shown.text} className="block truncate text-xs text-muted-foreground" />}
      </div>
      <StatusBadge status={shown.status} className="shrink-0" />
    </div>
  )
}

function Block({ heading, extra, children }: { heading: string; extra?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-lg border p-3">
      <div className="mb-1 flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">{heading}</h3>
        {extra}
      </div>
      <div className="divide-y">{children}</div>
    </section>
  )
}

interface Props {
  run: RunDetail
  gates?: Gate[]
  renderUnderStep?: (line: StepLine) => ReactNode
}

/** The read-only list of a run's steps: the start steps, one block per task, the end steps. */
export function StepList({ run, gates, renderUnderStep }: Props) {
  const open = gates ?? run.gates
  const title = (name: string) => planRow(run, name)?.title || name

  function rows(group: StepGroup, taskNo: number | null) {
    const task = taskNo === null ? undefined : run.tasks[String(taskNo)]
    const shownGate = new Set<string>()
    return groupNames(run, group).map((name) => {
      const line = latestLine(run, taskNo, name)
      const gate = gateFor(run, open, taskNo, line)
      const showGate = gate && !shownGate.has(gate.id) ? gate : undefined
      if (showGate) shownGate.add(showGate.id)
      return (
        <div key={name} data-step={name}>
          <StepRow title={title(name)} shown={describe(line, planRow(run, name), task)} />
          {showGate && (
            <div className="pb-2"><NeedsYouCard gate={showGate} compact /></div>
          )}
          {line && renderUnderStep?.(line)}
        </div>
      )
    })
  }

  const taskNumbers = Object.keys(run.tasks).map(Number).sort((a, b) => a - b)
  return (
    <div className="flex flex-col gap-3">
      {!run.plan_frozen && <Muted>Planned steps; the runner fixes them when the build starts.</Muted>}
      <Block heading="At the start">{rows("run-start", null)}</Block>
      {taskNumbers.map((n) => {
        const t = run.tasks[String(n)]!
        return (
          <Block
            key={n}
            heading={`Task ${n}: ${t.title}`}
            extra={
              <>
                <StatusBadge status={t.status} />
                {t.tries > 0 && (
                  <span className="text-xs text-muted-foreground">
                    attempt {t.tries} of {run.max_tries}
                  </span>
                )}
              </>
            }
          >
            {rows("task", n)}
          </Block>
        )
      })}
      <Block heading="At the end">{rows("run-finish", null)}</Block>
    </div>
  )
}
