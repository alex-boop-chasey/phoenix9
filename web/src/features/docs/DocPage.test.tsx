import { render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router"
import { afterEach, expect, it, vi } from "vitest"

import DocPage from "./DocPage"

function show(path: string) {
  const qc = new QueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/doc?path=${encodeURIComponent(path)}`]}><DocPage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

it("shows the title, the text and a Download link", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: true, data: { id: "run:r1/plan.md", title: "The plan", text: "# Hi\n\nSome **bold** text" } }))))
  show("run:r1/plan.md")
  expect(await screen.findByRole("heading", { name: "The plan" })).toBeTruthy()
  expect(screen.getByText("bold").tagName).toBe("STRONG")
  expect(screen.getByRole("link", { name: "Download" }).getAttribute("href")).toContain("docs/download?id=run%3Ar1%2Fplan.md")
})

it("shows the reason when the id is refused", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: false, message: "That is not a document id." }), { status: 400 })))
  show("../x")
  expect((await screen.findByRole("alert")).textContent).toContain("not a document id")
})
