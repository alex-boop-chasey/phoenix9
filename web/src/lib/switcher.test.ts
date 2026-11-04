import { describe, expect, it } from "vitest"

import { row } from "@/test/fixtures"
import { switchLine, switchState } from "./switcher"

describe("switcher", () => {
  it("shows a failed last build as Last build failed", () => {
    const p = row({ name: "a", last_build_failed: true })
    expect(switchState(p)).toBe("fail")
    expect(switchLine(p)).toBe("Last build failed")
  })
  it("running or waiting beats a failed last build", () => {
    const run = { run_id: "r", status: "running" as const, task: 1, tasks: 2 }
    expect(switchState(row({ name: "a", last_build_failed: true, run }))).toBe("run")
    expect(switchState(row({ name: "a", last_build_failed: true, needs_you: 1 }))).toBe("need")
  })
})
