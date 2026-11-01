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
  expect(screen.queryByLabelText("Model")).toBeNull()
  expect(screen.getByRole("button", { name: "Builder settings" })).toHaveAttribute("aria-expanded", "false")
})

test("shows effective values and provenance", async () => {
  setup()
  await open()
  expect(screen.getByLabelText("Model")).toHaveAttribute("placeholder", "claude-sonnet-5-5")
  expect(screen.getByLabelText("Fallback models")).toHaveAttribute("placeholder", "claude-haiku-5-5")
  expect(screen.getByLabelText("Max turns")).toHaveAttribute("placeholder", "40")
  expect(screen.getByText("from: preset:full")).toBeInTheDocument()
  expect(screen.getByText("from: library")).toBeInTheDocument()
  expect(document.querySelector("datalist#ai-builder-models option[value='claude-opus-5-5']")).not.toBeNull()
})

test("editing model reports a dotted change", async () => {
  const onChange = setup()
  await open()
  await userEvent.type(screen.getByLabelText("Model"), "x")
  expect(onChange).toHaveBeenCalledWith("steps.builder.model", "x")
  await userEvent.type(screen.getByLabelText("Tools"), "a")
  expect(onChange).toHaveBeenCalledWith("steps.builder.tools", ["a"])
  await userEvent.type(screen.getByLabelText("Max turns"), "5")
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
