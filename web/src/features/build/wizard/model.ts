// The build wizard's answers and every rule about them, as plain functions (no React).
import { getPath, sameValue } from "@/features/settings/dotted"
import type { LibraryStep, Overrides, PlanStep, PlanView, Preset, SettingsView, StepGroup } from "@/lib/types"

export const SLIDE_COUNT = 7
export const SLIDE_TITLES = [
  "What to build", "Preset", "Steps", "Models and tools", "Failures", "Finish", "Review and submit",
] as const

export type OnFailure = "continue" | "pause" | "delegate"
export type MergeMode = "auto" | "ask"

/** Everything the wizard asks; `steps` holds each switchable step's chosen on/off. */
export interface Answers {
  source: "spec" | "brief"
  spec: string
  brief: string
  preset: string
  basedOn: string | null
  steps: Record<string, boolean>
  /** AI edits by dotted key ("steps.builder.model"); only what the user typed. */
  ai: Record<string, unknown>
  maxTries: number
  /** The spending cap in dollars as typed; empty = no cap. */
  budget: string
  onFailure: OnFailure
  merge: MergeMode
  deploy: boolean
  /** The Planner's on/off before a brief forced it on, so going back to a spec puts it back. */
  plannerBeforeBrief: boolean | null
}

/** What the rules need to know besides the answers. */
export interface Context {
  project: string
  /** Library steps (name and default), the same for every preset. */
  steps: Pick<LibraryStep, "name" | "default">[]
  /** The plan for the chosen preset with no edits: what "differs" is measured against. */
  baseline?: PlanView | null
}

export interface WizardState {
  slide: number
  /** The furthest slide reached; the outline lets you jump back to any slide up to here. */
  seen: number
  answers: Answers
  remember: boolean
  error: string
}

export type Action =
  | { type: "next" } | { type: "back" } | { type: "goto"; slide: number }
  | { type: "source"; source: Answers["source"] }
  | { type: "spec"; path: string }
  | { type: "brief"; text: string }
  | { type: "preset"; preset: Preset }
  | { type: "step"; name: string; on: boolean }
  | { type: "ai"; key: string; value: unknown }
  | { type: "maxTries"; value: number }
  | { type: "budget"; value: string }
  | { type: "onFailure"; value: OnFailure }
  | { type: "merge"; value: MergeMode }
  | { type: "deploy"; on: boolean }
  | { type: "notify"; on: boolean }
  | { type: "remember"; on: boolean }
  | { type: "error"; message: string }

const PLANNER = "planner"
const NOTIFY = "notify"

/** Phoenix's own project always asks before merging. */
export const mergeLocked = (project: string) => project === "phoenix9"

/** Steps the wizard can switch (every step whose library default is not "always"). */
export const switchable = (ctx: Pick<Context, "steps">) => ctx.steps.filter((s) => s.default !== "always")

/** A step's on/off in a preset: the preset file's value, else the library default. */
export function presetStepOn(preset: Pick<Preset, "steps"> | undefined, step: Pick<LibraryStep, "name" | "default">) {
  return preset?.steps?.[step.name] ?? step.default !== "off"
}

/** Whether deploy settings mean "deploy after a build". */
export function deployIsOn(deploy: unknown): boolean {
  const d = (deploy ?? {}) as { with?: string; mode?: string }
  return !!d.with && d.with !== "none" && !!d.mode && d.mode !== "off"
}

/** The mode to send when Deploy is switched on: the saved mode if it is a deploying one ("button" from phase 4 stays), else on-merge. */
export function deployOnMode(deploy: unknown): string {
  const mode = (deploy as { mode?: string } | undefined)?.mode
  return mode === "on-merge" || mode === "button" ? mode : "on-merge"
}

/** Whether a deployer is chosen at all (else the Deploy switch is disabled). */
export const deployerChosen = (deploy: unknown) => {
  const w = (deploy as { with?: string } | undefined)?.with
  return !!w && w !== "none"
}

/** The typed spending cap as a number: undefined when empty, NaN when it is not a positive number. */
export function budgetValue(text: string): number | undefined {
  if (!text.trim()) return undefined
  const n = Number(text)
  return Number.isFinite(n) && n > 0 ? n : Number.NaN
}

/** Starting answers: the project's own saved settings. */
export function initialAnswers(settings: SettingsView, presets: Preset[], steps: Context["steps"]): Answers {
  const v = settings.values
  const preset = String(v.preset ?? "quick")
  const basedOn = preset === "custom" ? String(v.based_on ?? "quick") : null
  const presetRow = presets.find((p) => p.name === (basedOn ?? preset))
  const on: Record<string, boolean> = {}
  for (const s of switchable({ steps })) {
    const saved = getPath(v, `steps.${s.name}.on`)
    on[s.name] = typeof saved === "boolean" ? saved : presetStepOn(presetRow, s)
  }
  const merge = mergeLocked(settings.project) ? "ask" : (v.merge === "ask" ? "ask" : "auto")
  const onFailure = (["continue", "pause", "delegate"].includes(String(v.on_failure)) ? v.on_failure : "pause") as OnFailure
  return {
    source: "spec", spec: "", brief: "", preset, basedOn, steps: on, ai: {},
    maxTries: typeof v.max_tries === "number" ? v.max_tries : 3, onFailure, merge,
    budget: typeof v.budget_usd === "number" ? String(v.budget_usd) : "",
    deploy: deployIsOn(v.deploy), plannerBeforeBrief: null,
  }
}

/** Pick a preset: step on/off and per-step settings go back to that preset's values. */
export function applyPreset(a: Answers, preset: Preset, ctx: Pick<Context, "steps">): Answers {
  if (preset.name === "custom") {
    return { ...a, preset: "custom", basedOn: a.basedOn ?? (a.preset !== "custom" ? a.preset : "quick") }
  }
  const steps: Record<string, boolean> = {}
  for (const s of switchable(ctx)) steps[s.name] = presetStepOn(preset, s)
  if (a.source !== "brief") return { ...a, preset: preset.name, basedOn: null, steps, ai: {} }
  const plannerBeforeBrief = steps[PLANNER] ?? false
  return { ...a, preset: preset.name, basedOn: null, steps: { ...steps, [PLANNER]: true }, ai: {}, plannerBeforeBrief }
}

/** Switch one step: the preset becomes Custom, based on the preset it started from. */
export function setStep(a: Answers, name: string, on: boolean): Answers {
  if (name === PLANNER && a.source === "brief" && !on) return a
  if (a.steps[name] === on) return a
  const basedOn = a.preset === "custom" ? a.basedOn : a.preset
  return { ...a, steps: { ...a.steps, [name]: on }, preset: "custom", basedOn }
}

/**
 * Choose spec or brief. A brief switches the Planner on (it turns the brief into a spec); this is part of
 * "what to build", not a step edit, so the preset stays. Going back to a spec puts the Planner back.
 */
export function chooseSource(a: Answers, source: Answers["source"]): Answers {
  if (source === a.source) return a
  if (source === "brief") {
    return { ...a, source, steps: { ...a.steps, [PLANNER]: true }, plannerBeforeBrief: a.steps[PLANNER] ?? false }
  }
  const planner = a.plannerBeforeBrief ?? a.steps[PLANNER] ?? false
  return { ...a, source, steps: { ...a.steps, [PLANNER]: planner }, plannerBeforeBrief: null }
}

/** The pure reducer behind the wizard. */
export function reduce(state: WizardState, action: Action, ctx: Pick<Context, "project" | "steps">): WizardState {
  const a = state.answers
  const answers = (next: Answers): WizardState => ({ ...state, answers: next, error: "" })
  switch (action.type) {
    case "next": {
      const slide = Math.min(SLIDE_COUNT, state.slide + 1)
      return { ...state, slide, seen: Math.max(state.seen, slide) }
    }
    case "back": return { ...state, slide: Math.max(1, state.slide - 1) }
    case "goto":
      return action.slide >= 1 && action.slide <= state.seen ? { ...state, slide: action.slide } : state
    case "source": return answers(chooseSource(a, action.source))
    case "spec": return answers({ ...a, spec: action.path })
    case "brief": return answers({ ...a, brief: action.text })
    case "preset": return answers(applyPreset(a, action.preset, ctx))
    case "step": return answers(setStep(a, action.name, action.on))
    case "ai": {
      const ai = { ...a.ai }
      if (action.value === undefined) delete ai[action.key]
      else ai[action.key] = action.value
      return answers({ ...a, ai })
    }
    case "maxTries": return answers({ ...a, maxTries: action.value })
    case "budget": return answers({ ...a, budget: action.value })
    case "onFailure": return answers({ ...a, onFailure: action.value })
    case "merge": return answers({ ...a, merge: mergeLocked(ctx.project) ? "ask" : action.value })
    case "deploy": return answers({ ...a, deploy: action.on })
    case "notify": return answers({ ...a, steps: { ...a.steps, [NOTIFY]: action.on } })
    case "remember": return { ...state, remember: action.on }
    case "error": return { ...state, error: action.message }
  }
}

/** A fresh wizard on slide 1, not remembering as defaults until asked. */
export const startState = (answers: Answers): WizardState => ({ slide: 1, seen: 1, answers, remember: false, error: "" })

function setNested(target: Record<string, unknown>, dotted: string, value: unknown) {
  const parts = dotted.split(".")
  let node = target
  for (const part of parts.slice(0, -1)) {
    node[part] = (node[part] as Record<string, unknown> | undefined) ?? {}
    node = node[part] as Record<string, unknown>
  }
  node[parts.at(-1)!] = value
}

const meaningful = (v: unknown) =>
  v !== undefined && v !== "" && !(typeof v === "number" && Number.isNaN(v))

/** The baseline value of a dotted AI key ("steps.builder.model") from the preset's plan. */
function baselineAi(baseline: PlanView | null | undefined, key: string): unknown {
  const [, step, ...rest] = key.split(".")
  const row = baseline?.steps.find((s) => s.name === step)
  return getPath(row?.ai ?? undefined, rest.join("."))
}

/**
 * The overrides the server gets: the preset (+ based_on for custom), every switchable step's on/off,
 * and only the ai / run values that differ from the chosen preset's effective values.
 */
export function toOverrides(a: Answers, ctx: Context): Overrides {
  const out: Record<string, unknown> = { preset: a.preset }
  if (a.preset === "custom") out.based_on = a.basedOn ?? "quick"
  for (const s of switchable(ctx)) setNested(out, `steps.${s.name}.on`, a.steps[s.name] ?? presetStepOn(undefined, s))
  for (const [key, value] of Object.entries(a.ai)) {
    if (meaningful(value) && !sameValue(value, baselineAi(ctx.baseline, key))) setNested(out, key, value)
  }
  const base = ctx.baseline?.settings ?? {}
  if (a.maxTries !== base.max_tries) out.max_tries = a.maxTries
  if (a.onFailure !== base.on_failure) out.on_failure = a.onFailure
  if (a.merge !== base.merge) out.merge = a.merge
  const cap = budgetValue(a.budget)
  if (cap !== undefined && !Number.isNaN(cap) && cap !== base.budget_usd) out.budget_usd = cap
  if (a.deploy !== deployIsOn(base.deploy)) out.deploy = { mode: a.deploy ? deployOnMode(base.deploy) : "off" }
  return out
}

/** The run's start request: the spec or the brief, plus the overrides. */
export function startBody(a: Answers, overrides: Overrides) {
  return a.source === "spec" ? { spec: a.spec, overrides } : { brief: a.brief.trim(), overrides }
}

/** Why the user cannot leave slide `n` yet (empty when Next may be pressed). */
export function validateSlide(n: number, a: Answers, plan: Pick<PlanView, "errors"> | null | undefined): string[] {
  switch (n) {
    case 1:
      if (a.source === "spec" && !a.spec) return ["Choose a spec to build."]
      if (a.source === "brief" && !a.brief.trim()) return ["Write a short brief for the Planner."]
      return []
    case 3:
      if (!plan) return ["Working out the step list…"]
      return plan.errors
    case 5:
      return Number.isInteger(a.maxTries) && a.maxTries >= 1 && a.maxTries <= 10 ? [] : ["Tries must be a whole number from 1 to 10."]
    case 6:
      return Number.isNaN(budgetValue(a.budget)) ? ["The spending cap must be a number of dollars above 0, or empty."] : []
    default:
      return []
  }
}

/** Submit is allowed once every slide is fine and the plan and baseline have loaded. */
export function canSubmit(a: Answers, plan: PlanView | null | undefined, baseline: PlanView | null | undefined): boolean {
  if (!plan || !baseline) return false
  for (let n = 1; n <= SLIDE_COUNT; n++) if (validateSlide(n, a, plan).length) return false
  return true
}

/** The on/off a step list should show: forced-off steps show off, others the user's choice. */
export function shownStepValues(plan: PlanStep[], a: Answers): Record<string, boolean> {
  const out: Record<string, boolean> = {}
  for (const s of plan) {
    if (s.default === "always") continue
    out[s.name] = !s.on && s.reason.startsWith("needs ") ? false : (a.steps[s.name] ?? s.on)
  }
  return out
}

export const GROUP_TITLES: Record<StepGroup, string> = {
  "run-start": "At the start", task: "For every task", "run-finish": "At the end",
}

/** The plan in run order: start steps, the per-task steps, end steps (off steps included). */
export function planInOrder(plan: PlanStep[]): { group: StepGroup; title: string; steps: PlanStep[] }[] {
  return (["run-start", "task", "run-finish"] as StepGroup[]).map((group) => ({
    group, title: GROUP_TITLES[group],
    steps: plan.filter((s) => s.group === group).sort((x, y) => x.order - y.order),
  }))
}

/** The AI steps that will run (only these get a Models slide row). */
export const enabledAiSteps = (plan: PlanStep[]) =>
  plan.filter((s) => s.kind === "ai" && s.on).sort((x, y) => GROUP_RANK[x.group] - GROUP_RANK[y.group] || x.order - y.order)
const GROUP_RANK: Record<StepGroup, number> = { "run-start": 0, task: 1, "run-finish": 2 }

/** The preset's display name ("Custom, based on Quick"). */
export function presetLabel(a: Pick<Answers, "preset" | "basedOn">, presets: Preset[]): string {
  const title = (n: string) => {
    const t = presets.find((p) => p.name === n)?.title || n
    return t.charAt(0).toUpperCase() + t.slice(1)
  }
  return a.preset === "custom" ? `Custom, based on ${title(a.basedOn ?? "quick")}` : title(a.preset)
}

/** A step as the wizard's lists show it: the plan's row with the user's latest switch applied. */
export function shownOn(step: PlanStep, a: Pick<Answers, "steps">): boolean {
  if (step.default === "always") return true
  if (!step.on && step.reason.startsWith("needs ")) return false
  return a.steps[step.name] ?? step.on
}

export interface RunSummary {
  /** Switched-on steps by group, in run order; empty groups are left out. */
  groups: { group: StepGroup; title: string; names: string[] }[]
  /** Switched-off step names, and why (empty when nothing is off). */
  off: { names: string[]; note: string }
  /** Shown instead of a reason when the preset is Custom. */
  customHint: boolean
}

/** The "These steps will run" rail: on steps by group, then off steps with "Off in <preset>" or the Steps-page note. */
export function runSummary(plan: PlanStep[], a: Pick<Answers, "steps" | "preset" | "basedOn">, presets: Preset[]): RunSummary {
  const groups = planInOrder(plan)
    .map((g) => ({ group: g.group, title: g.title, names: g.steps.filter((s) => shownOn(s, a)).map((s) => s.title) }))
    .filter((g) => g.names.length)
  const names = planInOrder(plan).flatMap((g) => g.steps.filter((s) => !shownOn(s, a)).map((s) => s.title))
  const custom = a.preset === "custom"
  const presetTitle = presetLabel({ preset: a.preset, basedOn: a.basedOn }, presets)
  return {
    groups, customHint: custom,
    off: { names, note: custom ? "Switched off on the Steps page" : `Off in ${presetTitle}` },
  }
}

/** The small note under a step on the Steps slide (brief forces Planner; a missing step it needs), or "". */
export function stepNote(step: PlanStep, a: Pick<Answers, "source">, plan: PlanStep[]): string {
  if (step.name === PLANNER && a.source === "brief") return "On because you chose to write a brief on step 1"
  if (!step.on && step.reason.startsWith("needs ")) {
    const need = /^needs ([a-z0-9-]+)/.exec(step.reason)?.[1]
    const title = plan.find((s) => s.name === need)?.title ?? need
    return `Can't run: needs ${title} (switch it on)`
  }
  return ""
}

/** The AI steps to show cards for: every AI step that is switched on in the shown list. */
export const aiCards = (plan: PlanStep[], a: Pick<Answers, "steps">) =>
  plan.filter((s) => s.kind === "ai" && shownOn(s, a))
    .sort((x, y) => GROUP_RANK[x.group] - GROUP_RANK[y.group] || x.order - y.order)

/** Add, move or remove one entry of a list (fallback models). */
export function editList(list: string[], op: { add: string } | { up: number } | { down: number } | { remove: number }): string[] {
  const out = [...list]
  if ("add" in op) return op.add && !out.includes(op.add) ? [...out, op.add] : out
  if ("remove" in op) return out.filter((_, i) => i !== op.remove)
  const i = "up" in op ? op.up : op.down
  const j = "up" in op ? i - 1 : i + 1
  if (j < 0 || j >= out.length || i < 0 || i >= out.length) return out
  ;[out[i], out[j]] = [out[j]!, out[i]!]
  return out
}
