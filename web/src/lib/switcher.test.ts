import { describe, expect, it } from "vitest"

import { row } from "@/test/fixtures"
import { sortForSwitcher, switchLine, switchState } from "./switcher"

describe("switcher", () => {
  it("shows the backend's state and line, never its own guess", () => {
    // A row whose run says waiting but the backend says idle (the run was stopped): idle wins.
    const run = { run_id: "r", status: "waiting" as const, task: 1, tasks: 2 }
    const p = row({ name: "a", run, needs_you: 0, activity: "idle", status_line: "Idle, used 2h ago" })
    expect(switchState(p)).toBe("idle")
    expect(switchLine(p)).toBe("Idle, used 2h ago")
  })
  it("sorts needs-you, running, failed, idle, then by name", () => {
    const rows = [
      row({ name: "d", activity: "idle" }), row({ name: "c", activity: "fail" }),
      row({ name: "b", activity: "run" }), row({ name: "a2", activity: "need" }), row({ name: "a1", activity: "need" }),
    ]
    expect(sortForSwitcher(rows).map((r) => r.name)).toEqual(["a1", "a2", "b", "c", "d"])
  })
})
