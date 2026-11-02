import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import type { BuildRow, LogEntry } from "@/lib/types"
import { cn } from "@/lib/utils"

export const ALL = "__all__"
export const KINDS: LogEntry["kind"][] = ["session", "check", "diff", "step", "gate", "command", "service"]

export interface LogFilterValues {
  run: string
  task: string
  step: string
  kinds: string[]
}

/** Words for a task number (task 0 is the run itself). */
export const taskLabel = (n: number) => (n === 0 ? "Run level" : `Task ${n}`)

/** The label of a run in the Run select: date, title, result. */
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
    <Select value={value || ALL} onValueChange={(v) => onChange(v === ALL ? "" : v)}>
      <SelectTrigger aria-label={label} className="w-full">
        <SelectValue placeholder={label} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{all}</SelectItem>
        {!known && <SelectItem value={value}>{value}</SelectItem>}
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

/** Run, task and step dropdowns, kind chips and a Clear filters link (the parent keeps them in the URL). */
export function LogFilters({
  values, runs, tasks, steps, onChange, onClear,
}: {
  values: LogFilterValues
  runs: BuildRow[]
  tasks: number[]
  steps: string[]
  onChange: (patch: Partial<LogFilterValues>) => void
  onClear: () => void
}) {
  const active = !!(values.run || values.task || values.step || values.kinds.length)
  const toggle = (k: string) =>
    onChange({ kinds: values.kinds.includes(k) ? values.kinds.filter((x) => x !== k) : [...values.kinds, k] })
  return (
    <div className="flex flex-col gap-3">
      <Pick label="Run" value={values.run} all="All runs" onChange={(run) => onChange({ run, task: "", step: "" })}
        options={runs.map((b) => ({ value: b.run_id, label: runLabel(b) }))} />
      <Pick label="Task" value={values.task} all="All tasks" onChange={(task) => onChange({ task })}
        options={tasks.map((n) => ({ value: String(n), label: taskLabel(n) }))} />
      <Pick label="Step" value={values.step} all="All steps" onChange={(step) => onChange({ step })}
        options={steps.map((s) => ({ value: s, label: s }))} />
      <div role="group" aria-label="Kind" className="flex flex-wrap gap-1.5">
        {KINDS.map((k) => {
          const on = values.kinds.includes(k)
          return (
            <button key={k} type="button" aria-pressed={on} onClick={() => toggle(k)}
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-xs capitalize",
                on ? "border-primary bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent",
              )}>
              {k}
            </button>
          )
        })}
      </div>
      {active && (
        <Button variant="link" size="sm" className="self-start px-0" onClick={onClear}>Clear filters</Button>
      )}
    </div>
  )
}
