import type { FailedAt } from "@/lib/types"

import { badgeResult, resultText, rowBadge, rowResult } from "./parts"

const SUITE: FailedAt = {
  step: "full-suite", title: "Full suite", reason: "2 tests failed", text: "Failed at: Full suite: 2 tests failed",
}
const row = (over: Record<string, unknown> = {}) => ({
  status: "failed" as const, tasks_total: 3, tasks_failed: 0, current: null, failed_at: SUITE, ...over,
})

test("a failed build whose tasks all passed names the step it failed at", () => {
  expect(resultText("failed", 3, 0, null, SUITE)).toBe("Failed at: Full suite: 2 tests failed")
  expect(rowResult(row())).toBe("Failed at: Full suite: 2 tests failed")
})

test("task failures keep the task count, even when a run step failed too", () => {
  expect(resultText("failed", 3, 1, null, SUITE)).toBe("1 of 3 tasks failed")
  expect(rowBadge(row({ tasks_failed: 1 }))).toEqual({ text: "1 of 3 tasks failed", hint: undefined })
})

test("a failed build with no step named still says Failed", () => {
  expect(resultText("failed", 3, 0)).toBe("Failed")
  expect(rowResult(row({ failed_at: null }))).toBe("Failed")
})

test("the badge is short and its hover has the whole line", () => {
  expect(rowBadge(row())).toEqual({ text: "Failed at: Full suite", hint: "Failed at: Full suite: 2 tests failed" })
  expect(badgeResult("done", 0, "Passed", SUITE)).toEqual({ text: "Passed", hint: undefined })
})
