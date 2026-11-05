import { switchTool, toolState, usesDefaults } from "@/lib/tools"

const none = { tools: [], denied: [] }

test("empty lists mean the step's defaults, not everything off", () => {
  expect(usesDefaults(none)).toBe(true)
  expect(toolState(none, "Read")).toBe("default")
})

test("switching a tool off in the defaults denies it", () => {
  expect(switchTool(none, "Bash", false)).toEqual({ tools: [], denied: ["Bash"] })
  expect(toolState({ tools: [], denied: ["Bash"] }, "Bash")).toBe("off")
})

test("with an allowed list only listed tools are on", () => {
  const l = { tools: ["Read"], denied: [] }
  expect(toolState(l, "Read")).toBe("on")
  expect(toolState(l, "Edit")).toBe("off")
  expect(switchTool(l, "Edit", true)).toEqual({ tools: ["Read", "Edit"], denied: [] })
  expect(switchTool(l, "Read", false)).toEqual({ tools: [], denied: ["Read"] })
})

test("switching a denied tool on removes the denial", () => {
  expect(switchTool({ tools: [], denied: ["Bash"] }, "Bash", true)).toEqual(none)
})
