// Build tab test data: build rows and a run detail with a start step, three tasks and an end step.
import type { BuildRow, Gate, RunDetail, StepLine } from "@/lib/types"

import { builds as baseBuilds, gate } from "./fixtures"

const T0 = "2026-10-31T10:00:00Z"

export const build = (o: Partial<BuildRow>): BuildRow => ({
  ...baseBuilds[0]!, project: "demo-site", ...o,
})

export const BUILDS: BuildRow[] = [
  build({ run_id: "r-old", title: "Contact form", preset: "full", status: "done", started: "2026-10-20T09:00:00Z",
    duration: "14 min", cost: "$1.23", tasks_total: 3, tasks_passed: 3, tasks_failed: 0 }),
  build({ run_id: "r-fail", title: "Blog section", preset: "quick", status: "failed", started: "2026-10-22T14:00:00Z",
    duration: "20 min", cost: "$2.00", tasks_total: 5, tasks_passed: 3, tasks_failed: 2 }),
  build({ run_id: "r-wait", title: "Pricing page", preset: "full", status: "waiting", started: "2026-10-31T10:00:00Z",
    duration: "30 min", cost: "$0.80", tasks_total: 3, tasks_passed: 1, tasks_failed: 0 }),
]

export const line = (o: Partial<StepLine>): StepLine => ({
  group: "task", task: 1, step: "builder", attempt: 1, status: "passed", started: T0, finished: "2026-10-31T10:03:00Z",
  note: "", gate: null, ...o,
})

export const openGate: Gate = { ...gate, id: "r-wait.1", run: "r-wait", task: 2, step: "builder" }

export function runDetail(o: Partial<RunDetail> = {}): RunDetail {
  return {
    run_id: "r-wait", project: "demo-site", status: "waiting", created: T0, updated: T0,
    current: { group: "task", task: 2, step: "builder", attempt: 2, gate: openGate.id },
    tasks: {
      "1": { title: "Pricing table", status: "passed", tries: 1, failures: [], depends_on: [] },
      "2": { title: "Plan cards", status: "failed", tries: 2, failures: ["x"], depends_on: [1], gate: openGate.id },
      "3": { title: "Footer", status: "skipped", tries: 0, failures: [], depends_on: [2],
        note: "depends on task 2, which failed" },
    },
    steps: [
      line({ group: "run-start", task: null, step: "planner" }),
      line({ task: 1 }), line({ task: 1, step: "check" }),
      line({ task: 2, attempt: 1, status: "failed", note: "first try failed" }),
      line({ task: 2, attempt: 2, status: "failed", note: "the checks failed", gate: openGate.id }),
    ],
    usage: { cost_usd: 0.8, sessions: 3 }, gates: [openGate], recent_events: [],
    plan: {
      groups: { "run-start": ["planner"], task: ["builder", "check"], "run-finish": ["summary"] },
      steps: [
        { name: "planner", title: "Planner", group: "run-start", order: 10, on: true, reason: "" },
        { name: "builder", title: "Builder", group: "task", order: 10, on: true, reason: "" },
        { name: "check", title: "Check", group: "task", order: 20, on: true, reason: "" },
        { name: "review", title: "Review", group: "task", order: 30, on: false, reason: "switched off in the preset" },
        { name: "summary", title: "Summary", group: "run-finish", order: 20, on: true, reason: "" },
      ] as never,
    },
    plan_frozen: true, title: "Pricing page", preset: "full", max_tries: 3, ...o,
  }
}
