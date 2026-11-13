import { screen } from "@testing-library/react"

import { ProjectList } from "@/components/ProjectSwitcher"
import { projects } from "@/test/fixtures"
import { renderWithProviders } from "@/test/render"

test("the sidebar list shows the rows it is given, in groups", () => {
  renderWithProviders(<ProjectList rows={projects} />)
  for (const p of projects) expect(screen.getByText(p.name)).toBeInTheDocument()
  expect(screen.queryByText("home")).toBeNull()
})

test("sidebar rows have no Chat button, even for the current project", () => {
  const chat = { state: "awake" as const, bridge_session_id: "s1", web_url: null, app_url: null, last_active: null }
  const rows = projects.map((p) => ({ ...p, chat }))
  renderWithProviders(<ProjectList rows={rows} current={projects[0]!.name} />)
  expect(screen.queryByRole("button", { name: /Chat/ })).toBeNull()
  expect(screen.queryByRole("button", { name: "Sleep" })).toBeNull()
  expect(document.querySelector(".chatdot")).toBeNull()
})
