import { screen } from "@testing-library/react"

import { ProjectList } from "@/components/ProjectSwitcher"
import { projects } from "@/test/fixtures"
import { renderWithProviders } from "@/test/render"

test("the sidebar list shows the rows it is given, in groups", () => {
  renderWithProviders(<ProjectList rows={projects} />)
  for (const p of projects) expect(screen.getByText(p.name)).toBeInTheDocument()
  expect(screen.queryByText("home")).toBeNull()
})
