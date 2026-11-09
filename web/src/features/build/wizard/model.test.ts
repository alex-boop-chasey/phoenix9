import { wizardPresets, wizardSettings, wizardSteps, wizardPlan } from "@/test/wizardFixtures"

import {
  aiCards, editList, runSummary, shownOn, stepNote,
  applyPreset, canSubmit, deployOnMode, initialAnswers, reduce, startState, toOverrides, validateSlide, type Answers,
} from "./model"

const ctx = { project: "notes-only", steps: wizardSteps, baseline: wizardPlan() }
const start = (settings = wizardSettings()) => initialAnswers(settings, wizardPresets, wizardSteps)
const preset = (n: string) => wizardPresets.find((p) => p.name === n)!
const run = (a: Answers, ...actions: Parameters<typeof reduce>[1][]) =>
  actions.reduce((s, act) => reduce(s, act, ctx), startState(a)).answers

test("initial answers come from project settings", () => {
  const a = start(wizardSettings({ max_tries: 5, on_failure: "continue", merge: "ask", steps: { reviewer: { on: true } } }))
  expect(a.preset).toBe("quick")
  expect(a.basedOn).toBeNull()
  expect(a.maxTries).toBe(5)
  expect(a.onFailure).toBe("continue")
  expect(a.merge).toBe("ask")
  expect(a.steps.reviewer).toBe(true)
  expect(a.steps.verify).toBe(true)
  expect(a.steps.planner).toBe(false)
  expect(a.steps).not.toHaveProperty("builder")
  expect(a.deploy).toBe(false)
  expect(a.source).toBe("spec")
  const custom = start(wizardSettings({ preset: "custom", based_on: "full" }))
  expect(custom.basedOn).toBe("full")
})

test("apply preset resets steps and settings", () => {
  const edited = run(start(), { type: "step", name: "verify", on: false }, { type: "ai", key: "steps.builder.model", value: "m" })
  const a = applyPreset(edited, preset("full"), ctx)
  expect(a.preset).toBe("full")
  expect(a.basedOn).toBeNull()
  expect(a.steps).toMatchObject({ planner: true, reviewer: true, verify: true, "check-writer": true, notify: true })
  expect(a.ai).toEqual({})
  const simple = applyPreset(a, preset("simple"), ctx)
  expect(simple.steps).toMatchObject({ verify: false, reviewer: false, "diff-rules": true })
})

test("toOverrides sends preset, every switchable step on/off and only changed other values", () => {
  const a = run(start(),
    { type: "step", name: "reviewer", on: true },
    { type: "ai", key: "steps.builder.model", value: "claude-opus-5-5" },
    { type: "ai", key: "steps.reviewer.model", value: "claude-sonnet-5-5" },
    { type: "ai", key: "steps.builder.max_turns", value: Number.NaN },
    { type: "maxTries", value: 2 },
  )
  const o = toOverrides(a, ctx)
  expect(o.preset).toBe("custom")
  expect(o.based_on).toBe("quick")
  const steps = o.steps as Record<string, Record<string, unknown>>
  for (const s of wizardSteps.filter((x) => x.default !== "always")) expect(typeof steps[s.name]!.on).toBe("boolean")
  expect(steps).not.toHaveProperty("pick-up")
  expect(steps.builder).toEqual({ model: "claude-opus-5-5" })
  expect(steps.reviewer).toEqual({ on: true })
  expect(o.max_tries).toBe(2)
  expect(o).not.toHaveProperty("on_failure")
  expect(o).not.toHaveProperty("merge")
  expect(o).not.toHaveProperty("deploy")
  const plain = toOverrides(start(), ctx)
  expect(plain.preset).toBe("quick")
  expect(plain).not.toHaveProperty("based_on")
})

test("brief forces planner on", () => {
  const a = run(start(), { type: "source", source: "brief" })
  expect(a.steps.planner).toBe(true)
  expect(a.preset).toBe("quick")
  expect(run(a, { type: "step", name: "planner", on: false }).steps.planner).toBe(true)
  expect(applyPreset(a, preset("simple"), ctx).steps.planner).toBe(true)
  expect(run(a, { type: "source", source: "spec" }).steps.planner).toBe(false)
})

test("step edit switches preset to custom", () => {
  const a = run(start(), { type: "step", name: "reviewer", on: true })
  expect(a.preset).toBe("custom")
  expect(a.basedOn).toBe("quick")
  const again = run(a, { type: "step", name: "verify", on: false })
  expect(again.basedOn).toBe("quick")
  expect(run(start(), { type: "ai", key: "steps.builder.model", value: "x" }).preset).toBe("quick")
})

test("slide 1 needs spec or brief", () => {
  const a = start()
  expect(validateSlide(1, a, null)).not.toEqual([])
  expect(validateSlide(1, run(a, { type: "spec", path: "specs/reading-plan.md" }), null)).toEqual([])
  const brief = run(a, { type: "source", source: "brief" })
  expect(validateSlide(1, run(brief, { type: "brief", text: "   " }), null)).not.toEqual([])
  expect(validateSlide(1, run(brief, { type: "brief", text: "Add a page" }), null)).toEqual([])
})

test("slide 3 blocked while plan has errors", () => {
  const a = run(start(), { type: "spec", path: "specs/x.md" })
  expect(validateSlide(3, a, { errors: ["needs check-writer, which is off"] })).toEqual(["needs check-writer, which is off"])
  expect(validateSlide(3, a, { errors: [] })).toEqual([])
  expect(validateSlide(3, a, null)).toEqual(["Working out the step list…"])
  expect(validateSlide(3, a, undefined)).not.toEqual([])
  expect(canSubmit(a, { ...wizardPlan(), errors: ["bad"] }, wizardPlan())).toBe(false)
  expect(canSubmit(a, wizardPlan(), wizardPlan())).toBe(true)
  expect(canSubmit(a, wizardPlan(), null)).toBe(false)
})

test("retries limited 1 to 10", () => {
  const a = start()
  for (const ok of [1, 5, 10]) expect(validateSlide(5, run(a, { type: "maxTries", value: ok }), null)).toEqual([])
  for (const bad of [0, 11, 2.5, Number.NaN]) expect(validateSlide(5, run(a, { type: "maxTries", value: bad }), null)).not.toEqual([])
})

test("phoenix9 merge stays ask", () => {
  const settings = { ...wizardSettings({ merge: "auto" }), project: "phoenix9" }
  const a = initialAnswers(settings, wizardPresets, wizardSteps)
  expect(a.merge).toBe("ask")
  const s = reduce(startState(a), { type: "merge", value: "auto" }, { ...ctx, project: "phoenix9" })
  expect(s.answers.merge).toBe("ask")
  expect(run(start(), { type: "merge", value: "ask" }).merge).toBe("ask")
})

test("notifications map to steps.notify.on", () => {
  const a = run(start(), { type: "notify", on: false })
  expect(a.preset).toBe("quick")
  const steps = toOverrides(a, ctx).steps as Record<string, Record<string, unknown>>
  expect(steps.notify).toEqual({ on: false })
})

test("next and back stay within the seven slides", () => {
  let s = startState(start())
  s = reduce(s, { type: "back" }, ctx)
  expect(s.slide).toBe(1)
  for (let i = 0; i < 10; i++) s = reduce(s, { type: "next" }, ctx)
  expect(s.slide).toBe(7)
})

test("picking a preset uses the preset file, not the project's saved step switches", () => {
  // Saved settings switch Reviewer on; the server's /plan({preset}) would echo that back, the preset file does not.
  const a = start(wizardSettings({ steps: { reviewer: { on: true } } }))
  expect(a.steps.reviewer).toBe(true)
  const quick = applyPreset(applyPreset(a, preset("full"), ctx), preset("quick"), ctx)
  expect(quick.steps.reviewer).toBe(false)
  const baseline = wizardPlan({ preset: "quick" }, { steps: { reviewer: true } })
  const steps = toOverrides(quick, { ...ctx, baseline }).steps as Record<string, Record<string, unknown>>
  expect(steps.reviewer).toEqual({ on: false })
})

test("deploy keeps a saved button mode and is sent only when the switch changed", () => {
  expect(deployOnMode({ with: "netlify", mode: "button" })).toBe("button")
  expect(deployOnMode({ with: "netlify", mode: "on-merge" })).toBe("on-merge")
  expect(deployOnMode({ with: "netlify", mode: "off" })).toBe("on-merge")
  expect(deployOnMode(undefined)).toBe("on-merge")
  const button = wizardPlan({}, { deploy: { with: "netlify", mode: "button" } })
  const saved = start(wizardSettings({ deploy: { with: "netlify", mode: "button", preview: false } }))
  expect(saved.deploy).toBe(true)
  expect(toOverrides(saved, { ...ctx, baseline: button })).not.toHaveProperty("deploy")
  const off = run(saved, { type: "deploy", on: false })
  expect(toOverrides(off, { ...ctx, baseline: button }).deploy).toEqual({ mode: "off" })
  // A deployer chosen but mode off: switching on sends on-merge.
  const offBase = wizardPlan({}, { deploy: { with: "netlify", mode: "off" } })
  const on = run(start(), { type: "deploy", on: true })
  expect(toOverrides(on, { ...ctx, baseline: offBase }).deploy).toEqual({ mode: "on-merge" })
})

const plan = () => wizardPlan({ preset: "quick" }).steps

test("run summary groups what runs and says why the rest is off", () => {
  const a = start()
  const sum = runSummary(plan(), a, wizardPresets)
  expect(sum.groups.map((g) => g.title)).toEqual(["At the start", "For every task", "At the end"])
  expect(sum.groups[0]!.names).toEqual(["Pick up", "Spec check"])
  expect(sum.off.names).toEqual(expect.arrayContaining(["Planner", "Check writer", "Red check", "Reviewer"]))
  expect(sum.off.note).toBe("Off in Quick")
  expect(sum.customHint).toBe(false)
})

test("run summary follows the step switches and a switch makes it Custom", () => {
  const a = run(start(), { type: "step", name: "reviewer", on: true })
  const sum = runSummary(plan(), a, wizardPresets)
  expect(sum.groups[1]!.names).toContain("Reviewer")
  expect(sum.off.names).not.toContain("Reviewer")
  expect(sum.off.note).toBe("Switched off on the Steps page")
  expect(sum.customHint).toBe(true)
  expect(a.preset).toBe("custom")
  expect(a.basedOn).toBe("quick")
})

test("steps 2 and 3 share state: picking a preset changes what step 3 shows", () => {
  const a = run(start(), { type: "preset", preset: preset("full") })
  const reviewer = plan().find((s) => s.name === "reviewer")!
  expect(shownOn(reviewer, a)).toBe(true)
  expect(runSummary(plan(), a, wizardPresets).off.note).toBe("Off in Full")
})

test("always-on steps are always shown on", () => {
  const builder = plan().find((s) => s.name === "builder")!
  expect(shownOn(builder, { steps: { builder: false } })).toBe(true)
})

test("a step whose dependency is off shows off with a note naming the dependency", () => {
  const red = plan().find((s) => s.name === "red-check")!
  const a = start()
  expect(shownOn(red, { steps: { "red-check": true } })).toBe(false)
  expect(stepNote(red, a, plan())).toBe("Can't run: needs Check writer (switch it on)")
})

test("a brief forces the Planner on, shows a note, and cannot be switched off", () => {
  const a = run(start(), { type: "source", source: "brief" }, { type: "step", name: "planner", on: false })
  expect(a.steps.planner).toBe(true)
  const planner = plan().find((s) => s.name === "planner")!
  expect(stepNote(planner, a, plan())).toMatch(/write a brief/)
  const back = run(a, { type: "source", source: "spec" })
  expect(back.steps.planner).toBe(false)
})

test("a spec not in task format forces the Planner on with a note; a task-format spec leaves it free", () => {
  const a = run(start(), { type: "spec", path: "specs/app.md", needsPlanner: true }, { type: "step", name: "planner", on: false })
  expect(a.steps.planner).toBe(true)
  expect(a.preset).toBe("quick")
  const planner = plan().find((s) => s.name === "planner")!
  expect(stepNote(planner, a, plan())).toBe("This spec isn't in task format, so the Planner must be on to turn it into tasks")
  expect(applyPreset(a, preset("simple"), ctx).steps.planner).toBe(true)
  const tasks = run(a, { type: "spec", path: "specs/reading-plan.md", needsPlanner: false })
  expect(tasks.steps.planner).toBe(false)
  expect(stepNote(planner, tasks, plan())).toBe("")
  expect(run(tasks, { type: "step", name: "planner", on: true }).steps.planner).toBe(true)
})

test("AI cards: only AI steps that are switched on", () => {
  const names = (a: Answers) => aiCards(plan(), a).map((s) => s.name)
  expect(names(start())).toEqual(["builder"])
  expect(names(run(start(), { type: "step", name: "reviewer", on: true }))).toEqual(["builder", "reviewer"])
  expect(names(run(start(), { type: "preset", preset: preset("full") }))).toEqual(["planner", "check-writer", "builder", "reviewer"])
})

test("AI cards follow random custom mixes of switches", () => {
  let seed = 7
  const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648
  for (let i = 0; i < 30; i++) {
    const steps: Record<string, boolean> = {}
    for (const s of plan()) if (rnd() < 0.5) steps[s.name] = rnd() < 0.5
    const a = { ...start(), preset: "custom", steps }
    const cards = aiCards(plan(), a).map((s) => s.name)
    const expected = plan().filter((s) => s.kind === "ai" && shownOn(s, a)).map((s) => s.name)
    expect([...cards].sort()).toEqual([...expected].sort())
    expect(plan().filter((s) => s.kind !== "ai").some((s) => cards.includes(s.name))).toBe(false)
  }
})

test("fallback model list: add, move and remove", () => {
  const l = ["a", "b", "c"]
  expect(editList(l, { add: "d" })).toEqual(["a", "b", "c", "d"])
  expect(editList(l, { add: "a" })).toEqual(l)
  expect(editList(l, { up: 2 })).toEqual(["a", "c", "b"])
  expect(editList(l, { up: 0 })).toEqual(l)
  expect(editList(l, { down: 0 })).toEqual(["b", "a", "c"])
  expect(editList(l, { down: 2 })).toEqual(l)
  expect(editList(l, { remove: 1 })).toEqual(["a", "c"])
})

test("the outline only opens slides already reached", () => {
  const at = (n: number) => { let s = startState(start()); for (let i = 1; i < n; i++) s = reduce(s, { type: "next" }, ctx); return s }
  const s3 = at(3)
  expect(s3.seen).toBe(3)
  expect(reduce(s3, { type: "goto", slide: 1 }, ctx).slide).toBe(1)
  expect(reduce(reduce(s3, { type: "goto", slide: 1 }, ctx), { type: "goto", slide: 3 }, ctx).slide).toBe(3)
  expect(reduce(s3, { type: "goto", slide: 5 }, ctx).slide).toBe(3)
})
