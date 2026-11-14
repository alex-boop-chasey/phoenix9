import type { ReactNode } from "react"
import { Link } from "react-router"

import { Icon } from "@/components/Icon"
import { Indicator, type IndicatorKind } from "@/components/Indicator"
import { MergeReview } from "@/features/gates/MergeReview"
import { NeedsYouCard } from "@/features/gates/NeedsYouCard"
import { formatDuration, relativeTime } from "@/lib/format"
import type { Gate, ItemStatus, PlanStep, RunDetail, RunRepair, RunTask, StepGroup, StepLine } from "@/lib/types"

import { NoteButton } from "./NoteDialog"
import { Muted } from "./parts"
import { TaskTries } from "./TaskTries"

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

/** What a step says once its question is answered and the runner has not picked it up yet. */
export const CARRYING_ON = "Answered: Phoenix is carrying on"

function describe(line: StepLine | undefined, off: PlanStep | undefined, task: RunTask | undefined): Shown {
  if (off && !off.on && !line) return { status: "skipped", text: `Switched off (${off.reason || "switched off"})` }
  if (!line) {
    if (task?.status === "skipped") return { status: "skipped", text: task.note || "skipped" }
    return { status: "pending", text: "" }
  }
  if (line.answered) return { status: "running", text: CARRYING_ON }
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

/** The line to put a repair after: the latest step line that started before it (undefined: before every step). */
function anchorOf(run: RunDetail, repair: RunRepair): StepLine | undefined {
  const at = Date.parse(repair.at)
  let best: StepLine | undefined
  for (const l of run.steps) {
    const t = Date.parse(l.started)
    if (!Number.isFinite(t) || t > at) continue
    if (!best || t >= Date.parse(best.started)) best = l
  }
  return best
}

/** A grey line "repaired by <who>: <title>"; linked to its note in the Logs tab when there is a note file. */
function RepairLine({ run, repair }: { run: RunDetail; repair: RunRepair }) {
  const text = `repaired by ${repair.who}: ${repair.title}`
  const isNote = !!repair.note_id && repair.note_id.endsWith(".md")
  const to = `/p/${encodeURIComponent(run.project)}/logs?run=${encodeURIComponent(run.run_id)}&log=${encodeURIComponent(`${run.run_id}/repairs/notes/${repair.note_id}`)}`
  return (
    <p className="small muted" data-repair={repair.n}>
      {isNote ? <Link to={to}>{text}</Link> : text}
      {repair.rolled_back && " (rolled back)"}
    </p>
  )
}

/** The link to a task's task file (shown in the Logs tab). */
function TaskFileLink({ run, n }: { run: RunDetail; n: number }) {
  const id = `${run.run_id}/tasks/${n}/task.md`
  const to = `/p/${encodeURIComponent(run.project)}/logs?run=${encodeURIComponent(run.run_id)}&log=${encodeURIComponent(id)}`
  return <Link to={to} className="small" data-task-file={n}>Task file</Link>
}

const ENDED = ["done", "failed", "stopped"]

interface Props {
  run: RunDetail
  gates?: Gate[]
  renderUnderStep?: (line: StepLine) => ReactNode
  /** Show the "Planned steps" line and the "At the start" heading on top (default yes). */
  lead?: boolean
}

/** The clock of a running or waiting step ("Started 3 minutes ago"); the build summary shows the same words. */
export function liveClock(line: StepLine): string {
  if (line.status === "running" && line.answered) return "Answered"
  if (line.status === "running") return line.started ? `Started ${relativeTime(line.started)}` : "Running"
  if (line.status === "waiting") return line.started ? `Waiting ${relativeTime(line.started).replace(/ ago$/, "")}` : "Waiting"
  return ""
}

function timeOf(line: StepLine | undefined, shown: Shown): string {
  if (!line) return shown.status === "skipped" ? "Off" : "Pending"
  if (line.status === "running" || line.status === "waiting") return liveClock(line)
  return took(line) || (shown.status === "skipped" ? "Skipped" : "")
}

/** The lines above the first step: a note while the plan is not fixed yet, and the "At the start" heading. */
export function StepListLead({ run }: { run: RunDetail }) {
  return (
    <>
      {!run.plan_frozen && <Muted>Planned steps; the runner fixes them when the build starts.</Muted>}
      <h3 className="stack-h">At the start</h3>
    </>
  )
}

/** The stacked blocks of a run: the start steps, one group per task, the end steps. */
export function StepList({ run, gates, renderUnderStep, lead = true }: Props) {
  const open = gates ?? run.gates
  const title = (name: string) => planRow(run, name)?.title || name
  const repairs = run.repairs ?? []
  const anchors = new Map<StepLine | undefined, RunRepair[]>()
  for (const r of repairs) {
    const a = anchorOf(run, r)
    anchors.set(a, [...(anchors.get(a) ?? []), r])
  }
  const repairsAfter = (line: StepLine | undefined) =>
    (line ? anchors.get(line) ?? [] : []).map((r) => <RepairLine key={`repair-${r.n}`} run={run} repair={r} />)

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
        const block = (
          <Block
            title={heading} line={shown.text} time={timeOf(line, shown)} status={shown.status}
            plan={planRow(run, name)} room={mergeRoom}
          />
        )
        const room = (
          <div className="review-room" data-review-room>
            {showGate && (showGate.kind === "merge"
              ? <MergeReview gate={showGate} run={run} />
              : <NeedsYouCard gate={showGate} compact run={run} />)}
            {line && renderUnderStep?.(line)}
          </div>
        )
        return (
          <div key={`${name}-${line?.attempt ?? 0}`} data-step={name}>
            {mergeRoom ? <div className="need-card">{block}{room}</div> : block}
            {!mergeRoom && showGate && <div className="pt-2"><NeedsYouCard gate={showGate} compact run={run} /></div>}
            {!mergeRoom && line && renderUnderStep?.(line)}
            {repairsAfter(line)}
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
            <TaskTries run={run} n={n} stepTitle={title} />
          </div>
          <div className="blk-r"><Icon name="caret-right" size="sm" className="car" /></div>
        </summary>
        <div className="tg-in">
          <TaskFileLink run={run} n={n} />
          {blocks("task", n)}
        </div>
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
      {lead && <StepListLead run={run} />}
      {(anchors.get(undefined) ?? []).map((r) => <RepairLine key={`repair-${r.n}`} run={run} repair={r} />)}
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
              <TaskTries run={run} n={n} stepTitle={title} />
            </h3>
            <div className="row" style={{ gap: 12 }}>
              <TaskFileLink run={run} n={n} />
              {t.status === "running" && !ENDED.includes(run.status) && <NoteButton runId={run.run_id} task={n} />}
            </div>
            {blocks("task", n)}
          </div>
        )
      })}
      <h3 className="stack-h">At the end</h3>
      {blocks("run-finish", null)}
    </div>
  )
}
