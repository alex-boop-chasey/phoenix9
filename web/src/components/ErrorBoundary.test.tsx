import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { ErrorBoundary } from "@/components/ErrorBoundary"

let broken = true
function Fragile() {
  if (broken) throw new Error("kind is not known")
  return <p>All good</p>
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    broken = true
    vi.spyOn(console, "error").mockImplementation(() => {})
  })
  afterEach(() => vi.restoreAllMocks())

  it("shows the fallback when a child throws", () => {
    render(<ErrorBoundary><Fragile /></ErrorBoundary>)
    expect(screen.getByRole("alert")).toHaveTextContent("This part of the dashboard hit a problem.")
    expect(screen.getByText("kind is not known")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Back to projects" })).toBeInTheDocument()
  })

  it("Try again renders the child again", async () => {
    render(<ErrorBoundary><Fragile /></ErrorBoundary>)
    broken = false
    await userEvent.click(screen.getByRole("button", { name: "Try again" }))
    expect(screen.getByText("All good")).toBeInTheDocument()
    expect(screen.queryByRole("alert")).toBeNull()
  })

  it("clears the error when the reset key changes", () => {
    const { rerender } = render(<ErrorBoundary resetKey="/a"><Fragile /></ErrorBoundary>)
    expect(screen.getByRole("alert")).toBeInTheDocument()
    broken = false
    rerender(<ErrorBoundary resetKey="/b"><Fragile /></ErrorBoundary>)
    expect(screen.getByText("All good")).toBeInTheDocument()
  })
})
