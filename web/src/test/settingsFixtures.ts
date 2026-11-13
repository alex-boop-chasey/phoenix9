// Test data for the Settings tab: a project, its settings, plan, presets and library steps.
import { projects } from "@/test/fixtures"
import type { LibraryStep, PlanStep, PlanView, Preset, SettingsView } from "@/lib/types"

function step(over: Partial<PlanStep> & { name: string }): PlanStep {
  return {
    title: over.name, group: "task", order: 1, kind: "script", safety: false, default: "on", on: true,
    reason: "", sources: [], ai: null, ...over,
  }
}

export const libraryToolsData = {
  tools: [
    { name: "Read", label: "Read files", help: "Look at files in the project." },
    { name: "Edit", label: "Edit files", help: "Change parts of existing files." },
    { name: "Bash", label: "Run commands", help: "Run shell commands inside the step's container." },
    { name: "WebSearch", label: "Search the web", help: "Search the internet." },
  ],
}

export const planSteps: PlanStep[] = [
  step({ name: "builder", title: "Builder", order: 30, kind: "ai", default: "always" }),
  step({ name: "plan-check", title: "Plan check", group: "run-start", order: 10, kind: "gate" }),
  step({ name: "merge", title: "Merge", group: "run-finish", order: 90, kind: "gate", default: "always" }),
  step({ name: "reviewer", title: "Reviewer", order: 40, kind: "ai", safety: true }),
  step({ name: "check-writer", title: "Check writer", order: 20, kind: "ai", default: "off", on: false }),
  step({
    name: "check-fixer", title: "Check fixer", order: 35, kind: "ai", on: false,
    reason: "needs check-writer, which is off",
  }),
]

export const planView: PlanView = {
  groups: { "run-start": ["plan-check"], task: ["check-writer", "builder", "check-fixer", "reviewer"], "run-finish": ["merge"] },
  steps: planSteps, errors: [],
  settings: { preset: "full", max_tries: 3, on_failure: "pause", merge: "auto", deploy: "none" },
}

export const libraryDescriptions: Record<string, string> = {
  builder: "Writes the code for the task.", reviewer: "Reads the diff and flags problems.",
  "plan-check": "Checks the plan before work starts.", merge: "Merges the finished work.",
  "check-writer": "Writes the checks.", "check-fixer": "Fixes failing checks.",
}

export const libraryStepsData = {
  steps: planSteps.map((s): LibraryStep => ({
    name: s.name, title: s.title, kind: s.kind, group: s.group, default: s.default,
    description: libraryDescriptions[s.name] ?? "",
  })),
  problems: [],
}

export const presetsData = {
  presets: [
    { name: "simple", title: "Simple", has_file: true, description: "Build and merge." },
    { name: "quick", title: "Quick", has_file: true, description: "Build, check and merge." },
    { name: "full", title: "Full", has_file: true, description: "Every safety step." },
    { name: "custom", title: "Custom", has_file: false, description: "Your own mix." },
  ] as Preset[],
}

export const settingsView: SettingsView = {
  project: "demo-site",
  values: {
    preset: "full", merge: "auto", max_tries: 3, on_failure: "pause",
    deploy: { with: "none", mode: "off", preview: false },
    steps: {
      builder: { on: true, model: "claude-sonnet-5-5", fallback_models: ["claude-haiku-5-5"], tools: [], max_turns: 40, timeout: 30, advisor: { on: false, model: "", when: [], instructions: "" } },
      reviewer: { on: true, model: "claude-opus-5-5", fallback_models: [] },
    },
  },
  source: { "steps.builder.model": "library", "steps.reviewer.model": "preset:full", merge: "library" },
}

export const explainView = {
  project: "demo-site",
  text: "These steps run:\n  At the start:\n    Plan check\n  For every task:\n    Builder\nDiffers from defaults:\n  max_tries = 3",
}

const detail = projects[0]!
export const editedProject = { ...detail, changelog: [], gates: [] }

export const baseRoutes = (name = "demo-site") => ({
  [`GET /api/chat/${name}`]: { state: "none", bridge_session_id: null, web_url: null, app_url: null, last_active: null },
  [`GET /api/projects/${name}`]: { ...editedProject, name },
  [`GET /api/projects/${name}/settings`]: { ...settingsView, project: name },
  [`POST /api/projects/${name}/plan`]: planView,
  [`GET /api/projects/${name}/explain`]: { ...explainView, project: name },
  [`GET /api/projects/${name}/keys`]: [],
  "GET /api/library/presets": presetsData,
  "GET /api/library/steps": libraryStepsData,
  "GET /api/library/tools": libraryToolsData,
  "GET /api/library/services": { services: [{ name: "supabase", title: "Supabase", project_keys: [] }], problems: [] },
  "GET /api/library/templates": [],
  "GET /api/info": { version: "0.9.0", update: { supported: false, installed: "0.9.0", newest: "0.9.0", available: false, can_install: false, reason: "" }, github: { connected: true, accounts: ["rebirth-wd"] }, services: { supported: false } },
})
