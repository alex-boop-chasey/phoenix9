// Types for every `data` shape in docs/api.md. Field names are exactly the server's (snake_case).

export type RunStatus = "queued" | "running" | "waiting" | "paused-limit" | "done" | "failed" | "stopped"
export type ItemStatus = "pending" | "running" | "passed" | "failed" | "skipped" | "waiting"
export type AnyStatus = RunStatus | ItemStatus
export type StepGroup = "run-start" | "task" | "run-finish"

export interface Info {
  version: string
  update: {
    supported: boolean
    installed: string
    newest: string
    available: boolean
    can_install: boolean
    reason: string
    /** Paths (under api/) the server offers; a button shows only when its path is listed. */
    endpoints?: { install?: string; rollback?: string }
  }
  github: { connected: boolean; accounts: string[] }
  services: { supported: boolean }
}

export interface ActiveRun {
  run_id: string
  status: RunStatus
  task: number | null
  tasks: number
}

export interface ProjectRow {
  name: string
  description: string
  path: string
  repo: string
  repo_owner: string
  repo_name: string
  profile: string
  services: string[]
  size: number | null
  chat: { kind: "session" | "environment" | "none"; url: string | null }
  vscode_url: string
  state: "on" | "off"
  chats: number
  last_used: string
  last_used_at: string
  harness: string
  has_phoenix_toml: boolean
  repo_url: string | null
  needs_you: number
  run: ActiveRun | null
}

export interface ChangelogLine {
  date?: string
  who?: string
  text: string
}

export type GateKind = "merge" | "plan" | "human-task" | "escalation" | "deploy" | "step"
export type GateAction = "approve" | "back" | "skip" | "stop" | "acknowledged"

export interface Gate {
  id: string
  run: string
  project: string
  kind: GateKind
  title: string
  why: string
  task: number | null
  step: string | null
  links: { label: string; url: string }[]
  actions: GateAction[]
  flags: string[]
  created: string
  answered: boolean
}

export interface Project extends ProjectRow {
  changelog: ChangelogLine[]
  gates: Gate[]
}

export interface KeyRow {
  name: string
  secret: boolean
  has_value: boolean
  value_if_not_secret: string | null
}

export interface KeyInput {
  name: string
  value?: string
  secret: boolean
}

export type SettingSource = "library" | `profile:${string}` | `preset:${string}` | "project" | "run"

export interface SettingsView {
  project: string
  values: Record<string, unknown>
  source: Record<string, SettingSource>
}

export interface ExplainView {
  project: string
  text: string
}

export interface SpecFile {
  path: string
  title: string
  modified: string
}

export interface Usage {
  cost_usd?: number
  sessions?: number
}

export interface RunCurrent {
  group?: StepGroup | null
  task?: number | null
  step?: string | null
  attempt?: number | null
  gate?: string | null
}

export interface BuildRow {
  run_id: string
  project: string
  status: RunStatus
  created: string
  updated: string
  current: RunCurrent | null
  tasks_total: number
  tasks_passed: number
  usage: Usage
  title: string
  preset: string
  started: string
  finished: string
  duration: string
  cost: string
  tasks_failed: number
}

export interface RunTask {
  title: string
  status: ItemStatus
  tries: number
  failures: string[]
  depends_on: number[]
  escalations?: number
  flagged?: string | null
  gate?: string | null
  note?: string | null
}

export interface StepLine {
  group: StepGroup
  task: number | null
  step: string
  attempt: number | null
  status: ItemStatus
  started: string
  finished: string
  note?: string
  gate?: string | null
}

export interface PlanStep {
  name: string
  title: string
  group: StepGroup
  order: number
  kind: "script" | "ai" | "gate"
  safety: boolean | string
  default: "always" | "on" | "off"
  on: boolean
  reason: string
  sources: string[]
  ai: Record<string, unknown> | null
}

export interface PlanView {
  groups: Record<StepGroup, string[]>
  steps: PlanStep[]
  errors: string[]
  settings: {
    preset?: string
    based_on?: string | null
    max_tries?: number
    on_failure?: string
    merge?: string
    deploy?: string
  }
}

export interface RunDetail {
  run_id: string
  project: string
  status: RunStatus
  created: string
  updated: string
  current: RunCurrent
  tasks: Record<string, RunTask>
  steps: StepLine[]
  usage: Usage
  gates: Gate[]
  recent_events: PhoenixEvent[]
  plan: Partial<PlanView> & { off?: string[]; sources?: Record<string, unknown> }
  plan_frozen: boolean
  title: string
  preset: string
  max_tries: number
}

export type Overrides = Record<string, unknown>

export interface JobStep {
  label: string
  status: "running" | "done" | "failed"
}

export interface Job {
  id: string
  kind: "create"
  project: string
  status: "running" | "done" | "failed"
  steps: JobStep[]
  message: string
}

export interface LogEntry {
  id: string
  kind: "session" | "check" | "diff" | "step" | "gate" | "command" | "service"
  run: string
  task: number | null
  attempt: number | null
  step: string | null
  title: string
  size: number
  modified: string
}

export interface LogText {
  id: string
  kind: LogEntry["kind"]
  title: string
  text: string
  truncated: boolean
  is_diff: boolean
}

export interface PhoenixEvent {
  id: number
  ts: string
  type: string
  project: string | null
  run: string | null
  task: number | null
  step: string | null
  data: Record<string, unknown>
}

export interface EventsRecent {
  events: PhoenixEvent[]
  next: number
}

export interface LibraryStep {
  name: string
  title: string
  kind: "script" | "ai" | "gate"
  group: StepGroup
  default: "always" | "on" | "off"
  description: string
}

export interface Profile {
  name: string
  title: string
  image: string
}

export interface Preset {
  name: string
  title: string
  has_file: boolean
  description: string
}

export interface Template {
  name: string
  title: string
  profile: string
  kind: string
  check: string
}

export interface Service {
  name: string
  title: string
  project_keys: string[]
}

export interface GlobalView {
  values: Record<string, unknown>
  github: { connected: boolean; accounts: string[] }
  default_models: Record<string, { model: string; fallback_models: string[] }>
  telegram: { connected: boolean }
  supported: { services: boolean; update: boolean; secrets: boolean; github_connect?: boolean }
  /** Paths (under api/) the server offers for global writes. */
  endpoints?: { github_connect?: string }
}

export interface ServiceStatus {
  name: string
  title: string
  connected: boolean
  /** Paths (under api/) for this service's keys; the keys form uses them once the server lists them. */
  endpoints?: Record<string, string>
}

export interface ServicesView {
  supported: boolean
  services: ServiceStatus[]
}

export interface GithubRepos {
  connected: boolean
  repos: { full_name: string; owner: string; private: boolean }[]
}

export interface NameCheck {
  ok: boolean
  message: string
}

export interface CreateForm {
  name: string
  description: string
  source: { kind: "empty" | "repo" | "template" | "code"; repo?: string; template?: string; path?: string }
  profile: string
  new_repo: { on: boolean; owner: string }
  services: string[]
  keys: KeyInput[]
}

export interface EditBody {
  description?: string
  repo?: string
  profile?: string
  services?: string[]
  confirm?: boolean
}

export interface StartRunBody {
  spec?: string
  brief?: string
  overrides?: Overrides
}

export interface GateAnswer {
  gate: string
  action: GateAction
  note: string
  who: string
  at: string
}
