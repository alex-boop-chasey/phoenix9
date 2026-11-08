import { Icon, type IconName } from "@/components/Icon"
import type { BuildRow, LogEntry } from "@/lib/types"

export const ALL = ""
export const KINDS: LogEntry["kind"][] = ["session", "check", "diff", "step", "gate", "command", "service", "repair-note", "repair-report"]

/** Plain words and an icon for each kind of log. */
export const KIND_INFO: Record<LogEntry["kind"], { label: string; icon: IconName }> = {
  session: { label: "AI conversation", icon: "sparkle" },
  check: { label: "Check results", icon: "check-circle" },
  diff: { label: "Code changes", icon: "git-diff" },
  step: { label: "Step log", icon: "list-bullets" },
  gate: { label: "Questions", icon: "hand-palm" },
  command: { label: "Commands", icon: "terminal" },
  service: { label: "Service logs", icon: "hard-drives" },
  "repair-note": { label: "Repair note", icon: "list-bullets" },
  "repair-report": { label: "Run report", icon: "list-bullets" },
}

export interface LogFilterValues {
  run: string
  task: string
  step: string
  kinds: string[]
}

/** Words for a task number (task 0 is the build itself). */
export const taskLabel = (n: number) => (n === 0 ? "Build level" : `Task ${n}`)

/** The label of a build in the Build select: date, title, result. */
export function runLabel(b: BuildRow): string {
  return `${(b.started || b.created).slice(0, 10)} · ${b.title || b.run_id} · ${b.status}`
}

function Pick({
  label, value, onChange, all, options,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  all: string
  options: { value: string; label: string }[]
}) {
  const known = !value || options.some((o) => o.value === value)
  return (
    <>
      <label className="sr" htmlFor={`lg-${label}`}>{label}</label>
      <select id={`lg-${label}`} className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value={ALL}>{all}</option>
        {!known && <option value={value}>{value}</option>}
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </>
  )
}

/** Build, task and step dropdowns and Clear filters, then the kind chips (the parent keeps them in the URL). */
export function LogFilters({
  values, runs, tasks, steps, onChange, onClear, children,
}: {
  values: LogFilterValues
  runs: BuildRow[]
  tasks: number[]
  steps: string[]
  onChange: (patch: Partial<LogFilterValues>) => void
  onClear: () => void
  /** Sits on the right of the filter row (the Refresh button). */
  children?: React.ReactNode
}) {
  const toggle = (k: string) =>
    onChange({ kinds: values.kinds.includes(k) ? values.kinds.filter((x) => x !== k) : [...values.kinds, k] })
  return (
    <>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="lfil">
          <Pick label="Build" value={values.run} all="All builds" onChange={(run) => onChange({ run, task: "", step: "" })}
            options={runs.map((b) => ({ value: b.run_id, label: runLabel(b) }))} />
          <Pick label="Task" value={values.task} all="All tasks" onChange={(task) => onChange({ task })}
            options={tasks.map((n) => ({ value: String(n), label: taskLabel(n) }))} />
          <Pick label="Step" value={values.step} all="All steps" onChange={(step) => onChange({ step })}
            options={steps.map((s) => ({ value: s, label: s }))} />
          <button type="button" className="btn btn-ghost btn-sm" onClick={onClear}>Clear filters</button>
        </div>
        {children}
      </div>
      <div className="kinds" role="group" aria-label="Kinds of log">
        {KINDS.map((k) => (
          <button key={k} type="button" aria-pressed={values.kinds.includes(k)} onClick={() => toggle(k)}>
            <Icon name={KIND_INFO[k].icon} />{KIND_INFO[k].label}
          </button>
        ))}
      </div>
    </>
  )
}
