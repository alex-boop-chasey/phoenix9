// Test data matching the demo seed (docs/api.md "Demo data").
import type { BuildRow, Gate, GlobalView, Info, ProjectRow } from "@/lib/types"

export const info: Info = {
  version: "0.9.0",
  update: { supported: false, installed: "0.9.0", newest: "0.9.0", available: false, can_install: false, reason: "" },
  github: { connected: true, accounts: ["alex-boop-chasey", "rebirth-wd"] },
  services: { supported: false },
}

export function row(over: Partial<ProjectRow> & { name: string }): ProjectRow {
  return {
    description: "", path: `/srv/projects/${over.name}`, repo: "", repo_owner: "", repo_name: "", profile: "web",
    services: [], size: 1024, vscode_url: `https://code.example.test/?folder=/srv/projects/${over.name}`,
    vscode: { url: `https://code.example.test/?folder=/srv/projects/${over.name}`, reason: null },
    last_used: "", last_used_at: "", harness: "idle", has_phoenix_toml: true, repo_url: null, needs_you: 0,
    questions: [], run: null, last_build_failed: false, activity: "idle", status_line: "Idle", run_text: "Idle", ...over,
  }
}

export const projects: ProjectRow[] = [
  row({
    name: "demo-site", description: "A small marketing site for a pretend bakery.",
    size: 5 * 1024 * 1024, repo: "rebirth-wd/demo-site", repo_owner: "rebirth-wd", repo_name: "demo-site",
    repo_url: "https://github.com/rebirth-wd/demo-site", harness: "needs you", needs_you: 1,
    questions: ["20261031-100000-pricing-page.1"], activity: "need", status_line: "1 question waiting", run_text: "Waiting for you",
    run: { run_id: "20261031-100000-pricing-page", status: "waiting", task: 2, tasks: 3, carrying_on: false,
      why: "It is waiting for your answer.", now: "Now: waiting for you." },
  }),
  row({
    name: "tiny-tool", description: "A tiny command line tool that tidies CSV files.", size: null,
    repo: "alex-boop-chasey/tiny-tool", repo_owner: "alex-boop-chasey", repo_name: "tiny-tool",
    profile: "python-script", repo_url: "https://github.com/alex-boop-chasey/tiny-tool", harness: "running task 2 of 4",
    activity: "run", status_line: "Building, task 2 of 4", run_text: "Running task 2 of 4",
    run: { run_id: "20261101-080000-add-json-output", status: "running", task: 2, tasks: 4, carrying_on: false,
      why: "It is running.", now: "Now: working on task 2 of 4." },
  }),
  row({ name: "notes-only", description: "Research notes.", profile: "research" }),
  row({
    name: "phoenix9", repo: "alex-boop-chasey/phoenix9", repo_owner: "alex-boop-chasey", repo_name: "phoenix9",
    profile: "platform", repo_url: "https://github.com/alex-boop-chasey/phoenix9", harness: "needs you", needs_you: 1,
    questions: ["20261031-110000-api-and-dashboard.1"], activity: "need", status_line: "1 question waiting", run_text: "Waiting for you",
    run: { run_id: "20261031-110000-api-and-dashboard", status: "waiting", task: 1, tasks: 3, carrying_on: false,
      why: "It is waiting for your answer.", now: "Now: waiting for you." },
  }),
]

export const gate: Gate = {
  id: "20261031-100000-pricing-page.1", run: "20261031-100000-pricing-page", project: "demo-site",
  kind: "escalation", title: "Task 2 needs you", why: "Tried twice and failed.", task: 2, step: null,
  links: [], actions: ["acknowledged", "skip", "stop"], flags: [], created: "2026-10-31T10:30:00Z", answered: false,
}

export const builds: BuildRow[] = [
  {
    run_id: "20261020-090000-contact-form", project: "demo-site", status: "done",
    created: "2026-10-20T09:00:00Z", updated: "2026-10-20T09:14:00Z", current: null, tasks_total: 3, tasks_passed: 3,
    usage: { cost_usd: 1.23, sessions: 3 }, title: "Contact form", preset: "full", started: "2026-10-20T09:00:00Z",
    finished: "2026-10-20T09:14:00Z", duration: "14 min", cost: "$1.23", tasks_failed: 0,
  },
]

export const globalView: GlobalView = {
  values: {},
  github: { connected: true, accounts: ["rebirth-wd", "alex-boop-chasey"] },
  default_models: {
    planner: { model: "opus", fallback_models: ["sonnet"] },
    builder: { model: "sonnet", fallback_models: [] },
    "check-writer": { model: "sonnet", fallback_models: ["haiku"] },
    reviewer: { model: "opus", fallback_models: [] },
  },
  telegram: { connected: false },
  supported: { services: false, update: false, secrets: false },
  addresses: { dashboard_url: "https://phoenix.example.test/", allowed_origins: ["https://phoenix.example.test"], vscode_url: "" },
}

// Phoenix agent (docs/api.md "Agent items").
import type {
  AgentMessages, AgentSessionRow, AgentState, AgentStatus,
} from "@/features/agent/useAgent"

export function agentStatus(state: AgentState, over: Partial<AgentStatus> = {}): AgentStatus {
  const asleep = state === "asleep"
  return { state, pid: asleep ? null : 4242, session_id: asleep ? null : "sess-1", name: "phoenix", ...over }
}

export const agentStatuses: Record<AgentState, AgentStatus> = {
  asleep: agentStatus("asleep"),
  idle: agentStatus("idle"),
  working: agentStatus("working"),
  queued: agentStatus("queued"),
}

export const agentMessages: AgentMessages = {
  session_id: "sess-1",
  unknown: 0,
  last_line: 8,
  items: [
    { type: "user", line: 1, text: "Check the build", origin: "panel", at: "2026-11-07T10:00:00Z" },
    { type: "thinking", line: 2, duration_s: 4, at: "2026-11-07T10:00:04Z" },
    { type: "action", line: 3, id: "tool-1", tool: "Bash", title: "Run the tests", input_summary: "pytest -q", status: "running" },
    { type: "agent", line: 4, markdown: "Looking at **it** now.", at: "2026-11-07T10:00:09Z" },
    { type: "queued", line: 5, text: "Also the docs", pending: true, at: "2026-11-07T10:00:10Z" },
    { type: "notice", line: 6, text: "Context compacted" },
    { type: "session", line: 7, session_id: "sess-1" },
    { type: "user", line: 8, text: "From the app", origin: "app", at: "2026-11-07T10:01:00Z" },
  ],
}

export const agentSessions: AgentSessionRow[] = [
  { session_id: "sess-2", started: "2026-11-07T11:00:00Z", lines: 12 },
  { session_id: "sess-1", started: "2026-11-07T10:00:00Z", lines: 8 },
]
