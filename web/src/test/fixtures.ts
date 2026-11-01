// Test data matching the demo seed (docs/api.md "Demo data").
import type { BuildRow, Gate, Info, ProjectRow } from "@/lib/types"

export const info: Info = {
  version: "0.9.0",
  update: { supported: false, installed: "0.9.0", newest: "0.9.0", available: false, can_install: false, reason: "" },
  github: { connected: true, accounts: ["alex-boop-chasey", "rebirth-wd"] },
  services: { supported: false },
}

function row(over: Partial<ProjectRow> & { name: string }): ProjectRow {
  return {
    description: "", path: `/srv/projects/${over.name}`, repo: "", repo_owner: "", repo_name: "", profile: "web",
    services: [], size: 1024, chat: { kind: "none", url: null }, vscode_url: "", state: "off", chats: 0,
    last_used: "", last_used_at: "", harness: "idle", has_phoenix_toml: true, repo_url: null, needs_you: 0,
    run: null, ...over,
  }
}

export const projects: ProjectRow[] = [
  row({
    name: "demo-site", repo: "rebirth-wd/demo-site", repo_owner: "rebirth-wd", repo_name: "demo-site",
    repo_url: "https://github.com/rebirth-wd/demo-site", harness: "needs you", needs_you: 1,
    run: { run_id: "20261031-100000-pricing-page", status: "waiting", task: 2, tasks: 3 },
  }),
  row({
    name: "tiny-tool", repo: "alex-boop-chasey/tiny-tool", repo_owner: "alex-boop-chasey", repo_name: "tiny-tool",
    profile: "python-script", repo_url: "https://github.com/alex-boop-chasey/tiny-tool", harness: "running task 2 of 4",
    run: { run_id: "20261101-080000-add-json-output", status: "running", task: 2, tasks: 4 },
  }),
  row({ name: "notes-only", profile: "research" }),
  row({
    name: "phoenix9", repo: "alex-boop-chasey/phoenix9", repo_owner: "alex-boop-chasey", repo_name: "phoenix9",
    profile: "platform", repo_url: "https://github.com/alex-boop-chasey/phoenix9", harness: "needs you", needs_you: 1,
    run: { run_id: "20261031-110000-api-and-dashboard", status: "waiting", task: 1, tasks: 3 },
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
