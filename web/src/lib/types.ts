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
  chat: { state: "on" | "off"; kind: "session" | "environment" | "none"; url: string | null }
  vscode_url: string | null
  vscode: { url: string | null; reason: string | null }
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
export type KnownGateAction = "approve" | "back" | "skip" | "stop" | "acknowledged"
/** A gate's own extra action (for example "done") is any other word. */
export type GateAction = KnownGateAction | (string & {})

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

/** The reply of the projects search: attention rows first (if asked), the rest, and counts per status. */
export interface ProjectQueryResult {
  top: ProjectRow[]
  rest: ProjectRow[]
  total: number
  counts: { all: number; run: number; fail: number; idle: number; need: number }
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
    /** The effective [deploy] table (older fixtures use a plain string). */
    deploy?: string | { with?: string; mode?: string; preview?: boolean }
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
  kind: "create" | "deploy"
  project: string
  status: "running" | "done" | "failed"
  steps: JobStep[]
  message: string
  /** Deploy jobs: the deploy result once it has finished. */
  result?: DeployResult | null
}

/** One installed copy of Phoenix. */
export interface UpdateVersion {
  tag: string
  commit: string
}

/** GET /api/update: the updater's status. */
export interface UpdateStatus {
  supported: boolean
  installed: UpdateVersion | null
  previous: UpdateVersion | null
  newest: string | null
  update_available: boolean
  can_rollback: boolean
  busy: boolean
  busy_reason: string
  running: boolean
  waiting: string
  phase: string | null
  interrupted: boolean
  last: { action: string; tag: string | null; result: string; reason: string; at?: string } | null
  log_tail: string[]
}

/** The result of a deploy (a deploy record, or a skip / refusal). */
export interface DeployResult {
  ok: boolean
  message?: string
  reason?: string
  url?: string
  rolled_back?: boolean
  skipped?: string
}

/** One line of a project's deploy history. */
export interface DeployRecord {
  at: string
  commit: string
  version: string
  url: string
  ok: boolean
  rolled_back: boolean
  reason: string
  who: string
  deployer: string
}

/** GET /api/projects/<name>/deploys. */
export interface DeployStatus {
  project: string
  deployer: { name: string; title: string; supported: boolean }
  recent: DeployRecord[]
  live_url: string
  last_good_commit: string
  last_good_at: string
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
  /** {step: on} the preset file sets (empty for custom). */
  steps?: Record<string, boolean>
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
  description?: string
  support?: "store-and-wire" | "keys-only"
  connected: boolean
  /** Shown instead of a badge, e.g. "no account connection needed". */
  note?: string
  /** Fixed names of the account keys the connect form asks for. */
  account_keys?: string[]
  checked?: string
  checked_at?: string
  used_by?: string[]
  /** Paths (under api/) for this service: connect and disconnect. */
  endpoints?: { connect?: string; disconnect?: string }
}

export interface ConnectResult {
  name: string
  connected: boolean
  checked: string
  message: string
}

export interface KeysAudit {
  global: { file: string; names: string[]; used_by: string; modified: string; mode: string; mode_ok: boolean }[]
  projects: { project: string; name: string; secret: boolean; set: boolean; used: string; last_touched: string; service: string }[]
  problems: string[]
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
