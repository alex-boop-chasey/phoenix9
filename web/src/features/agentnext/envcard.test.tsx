// The .env card: names only, conflicts, one save as Alex, counts-only answer, no value anywhere.
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { vi } from "vitest"

import { ToolCall } from "./components"

const SECRET = "sk-live-topsecret-999"
const PUB = "https://public.example"
const ENV = `# c\nSTRIPE_KEY=${SECRET}\nAPI_URL=${PUB}\nOLD_KEY="${SECRET}-old"\n`
let sent: { url: string; body: string }[]
let logs: unknown[][]

beforeEach(() => {
  sent = []
  logs = []
  for (const m of ["log", "info", "warn", "error", "debug"] as const) vi.spyOn(console, m).mockImplementation((...a) => { logs.push(a) })
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    sent.push({ url: String(url), body: String(init?.body ?? "") })
    const data = String(url).endsWith("/keys") ? [{ name: "OLD_KEY", secret: true, has_value: true, value_if_not_secret: null }] : []
    return new Response(JSON.stringify({ ok: true, data }), { status: 200 })
  }))
})
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

const draw = (d: unknown = { project: "demo", why: "Needs keys" }) =>
  render(<ToolCall call={{ toolCallId: "e1", toolName: "ask_env_file", running: false, component: "EnvUploadCard", data: d }} />)
const answers = () => sent.filter((s) => s.url.includes("browser-results/e1")).map((s) => JSON.parse(s.body))
const upload = async () => {
  await userEvent.upload(screen.getByLabelText(/Choose a .env file/), new File([ENV], ".env"))
  await screen.findByText(/STRIPE_KEY/)
}

test("lists names with Secret/Public and a conflict, never a value", async () => {
  draw()
  await upload()
  expect(screen.getByText(/STRIPE_KEY: Secret/)).toBeInTheDocument()
  expect(screen.getByText(/API_URL: Public/)).toBeInTheDocument()
  expect(screen.getByText(/already set/)).toBeInTheDocument()
  expect(document.body.innerHTML).not.toContain(SECRET)
  expect(document.body.innerHTML).not.toContain(PUB)
})

test("keep existing is the default: Add keys saves the new names once and answers with counts", async () => {
  draw()
  await upload()
  await userEvent.click(screen.getByRole("button", { name: "Add keys" }))
  await waitFor(() => expect(answers()).toHaveLength(1))
  const save = sent.filter((s) => s.url.includes("/projects/demo/keys/save"))
  expect(save).toHaveLength(1)
  expect(JSON.parse(save[0]!.body).rows).toEqual([
    { name: "STRIPE_KEY", value: SECRET, secret: true },
    { name: "API_URL", value: PUB, secret: false },
  ])
  expect(answers()[0]).toEqual({ result: { status: "saved", added: 2, replaced: 0, kept: 1 } })
  expect(document.body.innerHTML).not.toContain(SECRET)
})

test("Replace sends the conflicting name too", async () => {
  draw()
  await upload()
  await userEvent.click(screen.getByLabelText("Replace"))
  await userEvent.click(screen.getByRole("button", { name: "Add keys" }))
  await waitFor(() => expect(answers()).toHaveLength(1))
  const rows = JSON.parse(sent.find((s) => s.url.includes("keys/save"))!.body).rows
  expect(rows.map((r: { name: string }) => r.name)).toContain("OLD_KEY")
  expect(answers()[0]).toEqual({ result: { status: "saved", added: 2, replaced: 1, kept: 0 } })
})

test("no value reaches the agent, the page or the console; Cancel answers cancelled", async () => {
  draw()
  await upload()
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }))
  await waitFor(() => expect(answers()).toHaveLength(1))
  expect(answers()[0]).toEqual({ result: { status: "cancelled" } })
  expect(sent.some((s) => s.url.includes("keys/save"))).toBe(false)
  for (const s of sent.filter((x) => x.url.includes("agent-next"))) expect(s.body).not.toContain(SECRET)
  expect(JSON.stringify(logs)).not.toContain(SECRET)
})

test("malformed data shows the fallback", () => {
  draw({ why: "x" })
  expect(screen.getByTestId("card-fallback")).toBeInTheDocument()
})
