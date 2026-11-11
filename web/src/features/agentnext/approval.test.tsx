// The approval card, the go_to move and the suggestion chips.
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

import { ApprovalCard, SuggestionChips, makeGoTo } from "./approval"

const item = { approvalId: "a1", toolName: "notifications-set", input: { name: "alpha", on: true }, decision: "pending" as const }

test("the card says exactly what will change and Approve sends approve", async () => {
  const seen: string[] = []
  render(<ApprovalCard item={item} onDecide={(d) => seen.push(d)} />)
  expect(screen.getByText("Build notifications for alpha: off → on")).toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Approve" }))
  expect(seen).toEqual(["approve"])
})

test("Deny sends deny", async () => {
  const seen: string[] = []
  render(<ApprovalCard item={item} onDecide={(d) => seen.push(d)} />)
  await userEvent.click(screen.getByRole("button", { name: "Deny" }))
  expect(seen).toEqual(["deny"])
})

test("after a decision the buttons are gone and the decision shows", () => {
  render(<ApprovalCard item={{ ...item, decision: "approve" }} onDecide={() => {}} />)
  expect(screen.queryByRole("button")).toBeNull()
  expect(screen.getByText("Approved.")).toBeInTheDocument()
})

test("other tools list each input as label and value", () => {
  render(<ApprovalCard item={{ ...item, toolName: "rename_thing", input: { new_name: "beta" } }} onDecide={() => {}} />)
  expect(screen.getByText("rename_thing")).toBeInTheDocument()
  expect(screen.getByText("new name:")).toBeInTheDocument()
  expect(screen.getByText("beta")).toBeInTheDocument()
})

test("the card shows the tool's plain description", () => {
  render(<ApprovalCard item={{ ...item, description: "Change one project setting." }} onDecide={() => {}} />)
  expect(screen.getByText("Change one project setting.")).toBeInTheDocument()
})

test("a change card has no typed field", () => {
  render(<ApprovalCard item={{ ...item, toolName: "set_models", input: { model: "sonnet", count: 2 } }} onDecide={() => {}} />)
  expect(screen.getByText("model:")).toBeInTheDocument()
  expect(screen.getByText("count:")).toBeInTheDocument()
  expect(screen.queryByRole("textbox")).toBeNull()
  expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled()
})

test("a destructive card blocks Approve until the right text is typed and sends it", async () => {
  const seen: [string, string | undefined][] = []
  const big = { ...item, toolName: "stop-build", input: { name: "alpha" }, confirmText: "alpha" }
  render(<ApprovalCard item={big} onDecide={(d, c) => seen.push([d, c])} />)
  const approve = screen.getByRole("button", { name: "Approve" })
  expect(approve).toBeDisabled()
  const field = screen.getByLabelText("Type alpha to confirm")
  await userEvent.type(field, "alph")
  expect(approve).toBeDisabled()
  await userEvent.type(field, "a")
  expect(approve).toBeEnabled()
  await userEvent.click(approve)
  expect(seen).toEqual([["approve", "alpha"]])
})

test("Deny works on a destructive card without typing", async () => {
  const seen: string[] = []
  render(<ApprovalCard item={{ ...item, confirmText: "alpha" }} onDecide={(d) => seen.push(d)} />)
  await userEvent.click(screen.getByRole("button", { name: "Deny" }))
  expect(seen).toEqual(["deny"])
})

test("go_to moves to a known page and an unknown page is refused", async () => {
  const moved: string[] = []
  const goTo = makeGoTo((h) => moved.push(h))
  expect(await goTo("go_to", { page: "p/alpha/build", params: { run: "r1" } })).toEqual({ ok: true, page: "p/alpha/build" })
  expect(moved).toEqual(["/p/alpha/build?run=r1"])
  const refused = await goTo("go_to", { page: "nowhere" })
  expect(refused.ok).toBe(false)
  expect(moved).toHaveLength(1)
})

test("a message chip sends, link chips open, other schemes are never shown", async () => {
  const sent: string[] = []
  const hashes: string[] = []
  const opened: string[] = []
  const open = vi.spyOn(window, "open").mockImplementation((u) => { opened.push(String(u)); return null })
  render(<SuggestionChips onSend={(m) => sent.push(m)} onHash={(h) => hashes.push(h)} actions={[
    { label: "Say hi", message: "hi" },
    { label: "Go home", link: "#/projects" },
    { label: "Docs", link: "https://example.com/x" },
    { label: "Chat", link: "claude://open/1" },
    { label: "Evil", link: "javascript:alert(1)" },
    { label: "Data", link: "data:text/html,x" },
    { label: "Ftp", link: "ftp://x/y" },
  ]} />)
  expect(screen.queryByText("Evil")).toBeNull()
  expect(screen.queryByText("Data")).toBeNull()
  expect(screen.queryByText("Ftp")).toBeNull()
  await userEvent.click(screen.getByText("Say hi"))
  await userEvent.click(screen.getByText("Go home"))
  await userEvent.click(screen.getByText("Docs"))
  await userEvent.click(screen.getByText("Chat"))
  expect(sent).toEqual(["hi"])
  expect(hashes).toEqual(["/projects"])
  expect(opened).toEqual(["https://example.com/x", "claude://open/1"])
  open.mockRestore()
})

test.each(["repair-skip-task", "repair-rewrite-checks"])("%s shows the why input as a Reason line", (toolName) => {
  render(<ApprovalCard item={{ ...item, toolName, input: { task: 3, why: "It needs a key we lack." } }} onDecide={() => {}} />)
  expect(screen.getByText("Reason: It needs a key we lack.")).toBeInTheDocument()
  expect(screen.queryByText("why:")).toBeNull()
})
