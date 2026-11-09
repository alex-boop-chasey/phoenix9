import { screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { StepToggleList } from "@/features/settings/StepToggleList"
import { mockApi } from "@/test/mockApi"
import { baseRoutes, planSteps } from "@/test/settingsFixtures"
import { renderWithProviders } from "@/test/render"

afterEach(() => vi.unstubAllGlobals())

async function renderList(props: Partial<React.ComponentProps<typeof StepToggleList>> = {}) {
  mockApi(baseRoutes())
  const onChange = vi.fn()
  renderWithProviders(<StepToggleList steps={planSteps} values={{}} onChange={onChange} {...props} />)
  await screen.findByText("Writes the code for the task.")
  return onChange
}

test("grouped run-start task run-finish in order", async () => {
  await renderList()
  const headings = screen.getAllByRole("heading").map((h) => h.textContent)
  expect(headings).toEqual(["At the start", "For every task", "At the end"])
  const task = screen.getByRole("region", { name: "For every task" })
  const titles = within(task).getAllByRole("listitem").map((li) => li.getAttribute("data-step"))
  expect(titles).toEqual(["check-writer", "builder", "check-fixer", "reviewer"])
})

test("safety badge on safety steps", async () => {
  await renderList()
  const reviewer = document.querySelector('[data-step="reviewer"]') as HTMLElement
  expect(within(reviewer).getByText("Safety")).toBeInTheDocument()
  expect(within(reviewer).getByText("AI")).toBeInTheDocument()
  const builder = document.querySelector('[data-step="builder"]') as HTMLElement
  expect(within(builder).queryByText("Safety")).toBeNull()
})

test("always-on steps show an Always on tag and no switch", async () => {
  const onChange = await renderList()
  const builder = document.querySelector('[data-step="builder"]') as HTMLElement
  expect(within(builder).getByText("Always on")).toBeInTheDocument()
  expect(within(builder).queryByRole("switch")).toBeNull()
  await userEvent.click(within(builder).getByText("Always on"))
  expect(onChange).not.toHaveBeenCalled()
  const reviewer = document.querySelector('[data-step="reviewer"]') as HTMLElement
  expect(within(reviewer).queryByText("Always on")).toBeNull()
  expect(within(reviewer).getByRole("switch")).toBeInTheDocument()
})

test("forced-off step shows reason and is disabled", async () => {
  await renderList()
  expect(screen.getByText("needs check-writer, which is off")).toBeInTheDocument()
  expect(screen.getByRole("switch", { name: "Check fixer" })).toBeDisabled()
  expect(screen.getByRole("switch", { name: "Check writer" })).toBeEnabled()
})

test("toggle calls onChange", async () => {
  const onChange = await renderList()
  await userEvent.click(screen.getByRole("switch", { name: "Reviewer" }))
  expect(onChange).toHaveBeenCalledWith("reviewer", false)
})

test("readOnly disables all", async () => {
  await renderList({ readOnly: true })
  for (const s of screen.getAllByRole("switch")) expect(s).toBeDisabled()
})
