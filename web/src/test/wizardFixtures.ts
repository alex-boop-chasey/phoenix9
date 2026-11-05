// Build wizard test data shaped like the demo library: steps, presets, settings, and a fake /plan.
import type { LibraryStep, PlanStep, PlanView, Preset, SettingsView, StepGroup } from "@/lib/types"

type Row = [name: string, title: string, group: StepGroup, order: number, kind: PlanStep["kind"], dflt: PlanStep["default"], safety?: boolean]

const ROWS: Row[] = [
  ["pick-up", "Pick up", "run-start", 10, "script", "always"],
  ["spec-check", "Spec check", "run-start", 20, "script", "always"],
  ["planner", "Planner", "run-start", 45, "ai", "off"],
  ["check-writer", "Check writer", "task", 10, "ai", "off"],
  ["red-check", "Red check", "task", 20, "script", "on", true],
  ["builder", "Builder", "task", 30, "ai", "always"],
  ["diff-rules", "Diff rules", "task", 40, "script", "on", true],
  ["verify", "Verify", "task", 70, "script", "on", true],
  ["reviewer", "Reviewer", "task", 80, "ai", "off"],
  ["summary", "Summary", "run-finish", 20, "script", "on"],
  ["merge", "Merge", "run-finish", 30, "script", "on"],
  ["notify", "Notify", "run-finish", 50, "script", "on"],
]

export const wizardSteps: LibraryStep[] = ROWS.map(([name, title, group, , kind, dflt]) => ({
  name, title, group, kind, default: dflt, description: `${title} does its job.`,
}))

export const wizardPresets: Preset[] = [
  { name: "simple", title: "Simple", has_file: true, description: "Just build each task and check it.",
    steps: { planner: false, "check-writer": false, verify: false, reviewer: false } },
  { name: "quick", title: "Quick", has_file: true, description: "Simple, plus the project's tests.",
    steps: { planner: false, "check-writer": false, verify: true, reviewer: false } },
  { name: "full", title: "Full", has_file: true, description: "Everything on.",
    steps: { planner: true, "check-writer": true, "red-check": true, verify: true, reviewer: true } },
  { name: "custom", title: "Custom", has_file: false, description: "Your own mix.", steps: {} },
]

const AI: Record<string, Record<string, unknown>> = {
  planner: { model: "claude-sonnet-5-5", fallback_models: ["claude-opus-5-5"], max_turns: 40 },
  "check-writer": { model: "claude-sonnet-5-5", fallback_models: [], max_turns: 40 },
  builder: { model: "claude-fable-5-1", fallback_models: ["claude-sonnet-5-5"], max_turns: 40 },
  reviewer: { model: "claude-sonnet-5-5", fallback_models: [], max_turns: 40 },
}

/** Project settings for notes-only (preset quick), with optional top-level changes. */
export function wizardSettings(over: Record<string, unknown> = {}, project = "notes-only"): SettingsView {
  const steps: Record<string, Record<string, unknown>> = {}
  const quick = wizardPresets[1]!.steps!
  for (const [name, , , , , dflt] of ROWS) steps[name] = { on: quick[name] ?? dflt !== "off", ...(AI[name] ?? {}) }
  const extra = (over.steps ?? {}) as Record<string, Record<string, unknown>>
  for (const [n, v] of Object.entries(extra)) steps[n] = { ...steps[n], ...v }
  return {
    project,
    values: {
      preset: "quick", based_on: "quick", merge: "auto", max_tries: 3, on_failure: "pause",
      deploy: { with: "none", mode: "off", preview: false }, ...over, steps,
    },
    source: {},
  }
}

/** What the project itself has saved (ranks above the preset, below the overrides, as on the server). */
export interface SavedLayer {
  steps?: Record<string, boolean>
  deploy?: { with?: string; mode?: string; preview?: boolean }
}

/** What POST /plan answers for these overrides (a tiny stand-in for the resolver). */
export function wizardPlan(overrides: Record<string, unknown> = {}, saved: SavedLayer = {}): PlanView {
  const presetName = String(overrides.preset === "custom" ? overrides.based_on ?? "quick" : overrides.preset ?? "quick")
  const preset = wizardPresets.find((p) => p.name === presetName)!
  const asked = (overrides.steps ?? {}) as Record<string, Record<string, unknown>>
  const wanted = (name: string, dflt: string) =>
    dflt === "always" ? true : (asked[name]?.on as boolean | undefined) ?? saved.steps?.[name] ?? preset.steps![name] ?? dflt !== "off"
  const steps: PlanStep[] = ROWS.map(([name, title, group, order, kind, dflt, safety]) => {
    let on = wanted(name, dflt)
    let reason = on ? "" : "switched off"
    if (name === "red-check" && on && !wanted("check-writer", "off")) {
      on = false
      reason = "needs check-writer, which is off"
    }
    const ai = AI[name] ? { ...AI[name], ...(asked[name] ?? {}) } : null
    if (ai) delete ai.on
    return { name, title, group, order, kind, safety: !!safety, default: dflt, on, reason, sources: [], ai }
  })
  const groups = { "run-start": [], task: [], "run-finish": [] } as Record<StepGroup, string[]>
  for (const s of steps) if (s.on) groups[s.group].push(s.name)
  return {
    groups, steps, errors: [],
    settings: {
      preset: String(overrides.preset ?? "quick"), based_on: (overrides.based_on as string) ?? presetName,
      max_tries: (overrides.max_tries as number) ?? 3, on_failure: (overrides.on_failure as string) ?? "pause",
      merge: (overrides.merge as string) ?? "auto",
      deploy: { with: "none", mode: "off", preview: false, ...saved.deploy, ...(overrides.deploy as object | undefined) },
    },
  }
}

export const wizardSpecs = [
  { path: "specs/reading-plan.md", title: "Reading plan", modified: "2026-11-01T09:00:00Z" },
  { path: "plans/older.md", title: "Older plan", modified: "2026-10-01T09:00:00Z" },
]
