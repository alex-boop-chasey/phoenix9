import type { ReactNode } from "react"

import { Icon } from "@/components/Icon"
import { Indicator, type IndicatorKind } from "@/components/Indicator"
import { MergeReview } from "@/features/gates/MergeReview"
import { NeedsYouCard } from "@/features/gates/NeedsYouCard"
import { formatDuration, relativeTime } from "@/lib/format"
import type { Gate, ItemStatus, PlanStep, RunDetail, RunTask, StepGroup, StepLine } from "@/lib/types"

import { Muted } from "./parts"

/** The latest attempt's line for a step (of one task, or of the run when task is null). */
function latestLine(run: RunDetail, task: number | null, step: string): StepLine | undefined {
  let best: StepLine | undefined
  for (const l of run.steps) {
    if (l.step !== step || (l.task ?? null) !== task) continue
    if (!best || (l.attempt ?? 0) >= (best.attempt ?? 0)) best = l
  }
  return best
}

/** Every attempt's line for a step (of one task, or of the run when task is null), oldest first. */
function allLines(run: RunDetail, task: number | null, step: string): StepLine[] {
  return run.steps
    .filter((l) => l.step === step && (l.task ?? null) === task)
    .sort((a, b) => (a.attempt ?? 0) - (b.attempt ?? 0))
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

/** The open merge question of a run whose Merge step is waiting (shown as the review under that step). */
function mergeGate(run: RunDetail, gates: Gate[]): Gate | undefined {
  if (latestLine(run, null, "merge")?.status !== "waiting") return undefined
  return gates.find((g) => g.kind === "merge" && !g.answered)
}

/** Ids of the open gates the step list shows itself (so a page can show only the others). */
export function gatesShownInSteps(run: RunDetail, gates: Gate[] = run.gates): Set<string> {
  const ids = new Set<string>()
  const merge = mergeGate(run, gates)
  if (merge) ids.add(merge.id)
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

const KIND: Record<ItemStatus, IndicatorKind> = {
  passed: "passed", failed: "failed", running: "running", waiting: "needs-you",
  pending: "pending", queued: "pending", skipped: "off",
} as never

const EDGE: Partial<Record<IndicatorKind, string>> = {
  running: "st-run", failed: "st-bad", pending: "st-pend", "needs-you": "st-need", off: "st-pend",
}

/** What the right-hand side of a block says about who does the step. */
function Model({ plan }: { plan: PlanStep | undefined }) {
  if (plan?.kind === "gate") return <span className="model"><Icon name="user" />you</span>
  if (plan?.kind === "ai") {
    const model = typeof plan.ai?.model === "string" ? plan.ai.model : "AI"
    return <span className="model"><Icon name="cpu" />{model}</span>
  }
  return <span className="model"><Icon name="terminal" />script</span>
}

interface BlockProps {
  title: string
  line: string
  time: string
  status: ItemStatus
  plan: PlanStep | undefined
  room?: boolean
}

/** One step as a block: indicator, title, what line, who runs it and how long it took. */
function Block({ title, line, time, status, plan, room }: BlockProps) {
  const kind = KIND[status] ?? "pending"
  return (
    <div className={`blk ${EDGE[kind] ?? ""} ${room ? "has-room" : ""}`} data-status={status}>
      <Indicator kind={kind} />
      <div className="blk-t">
        <b>{title}</b>
        {line && <span title={line}>{line}</span>}
      </div>
      <div className="blk-r">
        <Model plan={plan} />
        <small>{time}</small>
      </div>
    </div>
  )
}

interface Props {
  run: RunDetail
  gates?: Gate[]
  renderUnderStep?: (line: StepLine) => ReactNode
}

function timeOf(line: StepLine | undefined, shown: Shown): string {
  if (!line) return shown.status === "skipped" ? "Off" : "Pending"
  if (line.status === "running") return line.started ? `Started ${relativeTime(line.started)}` : "Running"
  if (line.status === "waiting") return line.started ? `Waiting ${relativeTime(line.started).replace(/ ago$/, "")}` : "Waiting"
  return took(line) || (shown.status === "skipped" ? "Skipped" : "")
}

/** The stacked blocks of a run: the start steps, one group per task, the end steps. */
export function StepList({ run, gates, renderUnderStep }: Props) {
  const open = gates ?? run.gates
  const title = (name: string) => planRow(run, name)?.title || name

  function blocks(group: StepGroup, taskNo: number | null) {
    const task = taskNo === null ? undefined : run.tasks[String(taskNo)]
    const shownGate = new Set<string>()
    return groupNames(run, group).flatMap((name) => {
      const lines = allLines(run, taskNo, name)
      const list: (StepLine | undefined)[] = lines.length ? lines : [undefined]
      return list.map((line, i) => {
        const last = i === list.length - 1
        const isMerge = taskNo === null && name === "merge" && line?.status === "waiting"
        const gate = last ? (isMerge ? mergeGate(run, open) : gateFor(run, open, taskNo, line)) : undefined
        const showGate = gate && !shownGate.has(gate.id) ? gate : undefined
        if (showGate) shownGate.add(showGate.id)
        const shown = describe(line, planRow(run, name), task)
        if (name === "merge" && line?.status === "passed" && !line.note) shown.text = "Merged into main"
        const many = list.length > 1 || (line?.attempt ?? 1) > 1
        const heading = many && line?.attempt ? `${title(name)}, attempt ${line.attempt}` : title(name)
        const mergeRoom = line?.status === "waiting" && name === "merge"
        return (
          <div key={`${name}-${line?.attempt ?? 0}`} data-step={name}>
            <Block
              title={heading} line={shown.text} time={timeOf(line, shown)} status={shown.status}
              plan={planRow(run, name)} room={mergeRoom}
            />
            {mergeRoom && (
              <div className="review-room" data-review-room>
                {showGate && (showGate.kind === "merge"
                  ? <MergeReview gate={showGate} />
                  : <NeedsYouCard gate={showGate} compact />)}
                {line && renderUnderStep?.(line)}
              </div>
            )}
            {!mergeRoom && showGate && <div className="pt-2"><NeedsYouCard gate={showGate} compact /></div>}
            {!mergeRoom && line && renderUnderStep?.(line)}
          </div>
        )
      })
    })
  }

  function finishedTask(n: number) {
    const t = run.tasks[String(n)]!
    const names = groupNames(run, "task").filter((s) => allLines(run, n, s).length > 0)
    const count = names.length
    return (
      <details className="tg" key={n} data-task={n}>
        <summary className="blk">
          <Indicator kind="passed" />
          <div className="blk-t">
            <b>Task {n} · {t.title}</b>
            <span>{count} {count === 1 ? "step" : "steps"} passed</span>
          </div>
          <div className="blk-r"><Icon name="caret-right" size="sm" className="car" /></div>
        </summary>
        <div className="tg-in">{blocks("task", n)}</div>
      </details>
    )
  }

  function idleTask(n: number) {
    const t = run.tasks[String(n)]!
    const skipped = t.status === "skipped"
    return (
      <div className="blk st-pend" key={n} data-task={n}>
        <Indicator kind={skipped ? "off" : "pending"} />
        <div className="blk-t">
          <b>Task {n} · {t.title}</b>
          <span>{skipped ? t.note || "Skipped" : "Not started"}</span>
        </div>
      </div>
    )
  }

  const taskNumbers = Object.keys(run.tasks).map(Number).sort((a, b) => a - b)
  const hasOpenGate = (n: number) => groupNames(run, "task").some((s) => gateFor(run, open, n, allLines(run, n, s).at(-1)))
  return (
    <div className="stack" aria-live="polite">
      {!run.plan_frozen && <Muted>Planned steps; the runner fixes them when the build starts.</Muted>}
      <h3 className="stack-h">At the start</h3>
      {blocks("run-start", null)}
      {taskNumbers.map((n) => {
        const t = run.tasks[String(n)]!
        const started = run.steps.some((l) => l.task === n)
        if (t.status === "passed" && !hasOpenGate(n)) return finishedTask(n)
        if (!started) return idleTask(n)
        return (
          <div className="stack" key={n} data-task={n}>
            <h3 className="stack-h">
              Task {n} · {t.title}
              {t.tries > 0 && <span className="small">attempt {t.tries} of {run.max_tries}</span>}
            </h3>
            {blocks("task", n)}
          </div>
        )
      })}
      <h3 className="stack-h">At the end</h3>
      {blocks("run-finish", null)}
    </div>
  )
}
