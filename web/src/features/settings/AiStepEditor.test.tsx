import { screen } from "@testing-library/react"
import { render } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { AiStepEditor } from "@/features/settings/AiStepEditor"
import type { SettingSource } from "@/lib/types"

const effective = {
  model: "claude-sonnet-5-5", fallback_models: ["claude-haiku-5-5"], max_turns: 40, timeout: 30,
  advisor: { on: false, model: "claude-opus-5-5", when: [], instructions: "" },
}
const source: Record<string, SettingSource> = { "steps.builder.model": "preset:full", "steps.builder.max_turns": "library" }

function setup(changes: Record<string, unknown> = {}) {
  const onChange = vi.fn()
  render(
    <AiStepEditor
      step="builder" title="Builder" effective={effective} source={source} changes={changes}
      onChange={onChange} models={["claude-sonnet-5-5", "claude-opus-5-5"]}
    />,
  )
  return onChange
}
const open = () => userEvent.click(screen.getByRole("button", { name: "Builder settings" }))

test("collapsed by default", () => {
  setup()
  expect(screen.queryByLabelText("Primary model")).toBeNull()
  expect(screen.getByRole("button", { name: "Builder settings" })).toHaveAttribute("aria-expanded", "false")
})

test("shows effective values and provenance", async () => {
  setup()
  await open()
  expect(screen.getByLabelText("Primary model")).toHaveValue("claude-sonnet-5-5")
  expect(screen.getByLabelText("Backup model (optional)")).toHaveValue("claude-haiku-5-5")
  expect(screen.getByLabelText("Turn limit")).toHaveAttribute("placeholder", "40")
  expect(screen.getByText(/whichever comes first/)).toBeInTheDocument()
  expect(screen.getByText("from: preset:full")).toBeInTheDocument()
  expect(screen.getByText("from: library")).toBeInTheDocument()
  expect(screen.getAllByRole("option", { name: "claude-opus-5-5", hidden: true }).length).toBeGreaterThan(0)
})

test("editing model reports a dotted change", async () => {
  const onChange = setup()
  await open()
  await userEvent.selectOptions(screen.getByLabelText("Primary model"), "claude-opus-5-5")
  expect(onChange).toHaveBeenCalledWith("steps.builder.model", "claude-opus-5-5")
  await userEvent.selectOptions(screen.getByLabelText("Backup model (optional)"), "None")
  expect(onChange).toHaveBeenCalledWith("steps.builder.fallback_models", [])
  await userEvent.type(screen.getByLabelText("Tools"), "a")
  expect(onChange).toHaveBeenCalledWith("steps.builder.tools", ["a"])
  await userEvent.type(screen.getByLabelText("Turn limit"), "5")
  expect(onChange).toHaveBeenCalledWith("steps.builder.max_turns", 5)
})

test("advisor fields", async () => {
  const onChange = setup()
  await open()
  await userEvent.click(screen.getByRole("switch", { name: "Advisor on" }))
  expect(onChange).toHaveBeenCalledWith("steps.builder.advisor.on", true)
  await userEvent.click(screen.getByRole("checkbox", { name: "Before done" }))
  expect(onChange).toHaveBeenCalledWith("steps.builder.advisor.when", ["before-done"])
  await userEvent.type(screen.getByLabelText("Advisor instructions"), "y")
  expect(onChange).toHaveBeenCalledWith("steps.builder.advisor.instructions", "y")
  expect(screen.getByLabelText("Advisor model")).toHaveAttribute("placeholder", "claude-opus-5-5")
})

test("tool switches show the step's real tools from the library layer", async () => {
  const toolList = ["Read", "Edit", "Write", "Glob", "Grep", "Bash", "WebFetch", "WebSearch"].map((name) => ({ name, label: name, help: "" }))
  const plannerEffective = { ...effective, tools: ["Read", "Glob", "Grep", "Write"], tools_denied: ["Bash", "WebFetch", "WebSearch"] }
  const onChange = vi.fn()
  render(
    <AiStepEditor
      step="planner" title="Planner" effective={plannerEffective} changes={{}} onChange={onChange} toolList={toolList}
      source={{ "steps.planner.tools": "library", "steps.planner.tools_denied": "library" }}
    />,
  )
  await userEvent.click(screen.getByRole("button", { name: "Planner settings" }))
  for (const t of ["Read", "Glob", "Grep", "Write"]) expect(screen.getByRole("switch", { name: t })).toBeChecked()
  for (const t of ["Edit", "Bash", "WebFetch", "WebSearch"]) expect(screen.getByRole("switch", { name: t })).not.toBeChecked()
  expect(screen.queryByText(/Using this step's default tools/)).toBeNull()
  await userEvent.click(screen.getByRole("switch", { name: "Bash" }))
  expect(onChange).toHaveBeenCalledWith("steps.planner.tools", ["Read", "Glob", "Grep", "Write", "Bash"])
  expect(onChange).toHaveBeenCalledWith("steps.planner.tools_denied", ["WebFetch", "WebSearch"])
})
