import { ringFill, toGo } from "./progress"

test("the ring is true to time, then slows and never reaches full", () => {
  expect(ringFill(0)).toBe(0)
  expect(ringFill(0.5)).toBe(0.5)
  expect(ringFill(0.8)).toBeCloseTo(0.8)
  expect(ringFill(1)).toBeLessThan(0.95)
  expect(ringFill(10)).toBeLessThan(0.95)
  expect(ringFill(1.2)).toBeGreaterThan(ringFill(1))
})

test("time left in plain words", () => {
  expect(toGo(10)).toBe("about 1 min to go")
  expect(toGo(170)).toBe("about 3 min to go")
  expect(toGo(80 * 60)).toBe("about 1 h 20 min to go")
})
