import { formatBytes, formatCost, formatDuration, relativeTime } from "@/lib/format"

test("bytes", () => {
  expect(formatBytes(null)).toBe("-")
  expect(formatBytes(512)).toBe("512 B")
  expect(formatBytes(1536)).toBe("1.5 KB")
  expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB")
  expect(formatBytes(50 * 1024 * 1024)).toBe("50 MB")
})

test("duration", () => {
  expect(formatDuration(45)).toBe("45s")
  expect(formatDuration(14 * 60)).toBe("14 min")
  expect(formatDuration(2 * 3600 + 10 * 60)).toBe("2 h 10 min")
  expect(formatDuration(109 * 3600 + 39 * 60 + 56)).toBe("4 days")
  expect(formatDuration(5 * 86400)).toBe("5 days")
  expect(formatDuration(86400)).toBe("1 day")
  expect(formatDuration(2 * 3600 + 5 * 60)).toBe("2 h 5 min")
  expect(formatDuration(3600)).toBe("1 h")
  expect(formatDuration(null)).toBe("-")
})

test("cost", () => {
  expect(formatCost(1.234)).toBe("$1.23")
  expect(formatCost(0)).toBe("$0.00")
  expect(formatCost(undefined)).toBe("-")
})

test("relative time", () => {
  const now = Date.parse("2026-11-01T12:00:00Z")
  expect(relativeTime("2026-11-01T11:55:00Z", now)).toBe("5 minutes ago")
  expect(relativeTime("2026-10-30T12:00:00Z", now)).toBe("2 days ago")
})
