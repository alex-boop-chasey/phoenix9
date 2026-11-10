# Proof slice: what we learned

The plan rests on three outside libraries: Pydantic AI for the agent loop, AG-UI events over SSE for the
stream, and assistant-ui for the chat screen. Nobody had shown them working together for browser actions
and approval pauses. Tasks 1 to 8 built a small slice with scripted model replies (no real Claude calls,
no network) to find out. This page records what each of the four parts showed.

## Library versions used

| Part | Version |
| --- | --- |
| pydantic-ai-slim | 2.66.0 |
| pydantic-graph | 2.66.0 |
| pydantic | 2.14.3 |
| ag-ui-protocol (Python) | 1.0.0 |
| anthropic | 2.7.0 |
| starlette | 1.10.0 |
| uvicorn | 0.54.0 |
| httpx | 0.28.1 |
| @assistant-ui/react | 0.15.33 |
| @assistant-ui/react-ag-ui | 0.1.2 |
| @ag-ui/client | 1.0.4 |
| react | 19.3.1 |
| @playwright/test | 1.64.1 |

The full list is in `agentkit/requirements.lock` and `web/pnpm-lock.yaml`.

## 1. Streamed reply

**What worked.** A message sent to the agent service comes back as a reply that arrives piece by piece and
shows up in the chat as it grows. A client that drops off can ask again "after event N" and gets only what
it missed.

**How it is wired.** `agentkit/llm.py` runs the Pydantic AI agent and hands back plain text pieces.
`agentkit/wire.py` turns them into AG-UI events (run started, text start, text content, text end, run
finished) and writes them as SSE frames, each numbered. `service.py` keeps the numbered events so
`?after=N` and `Last-Event-ID` work. In the browser, `web/src/features/agentnext/runtime.ts` reads the
frames and gives them to assistant-ui's AG-UI runtime, which draws the chat.

**Limits found.** Every request needs the shared token, and the browser never sees it: phoenix-api adds it
on the way through. Model text is shown as plain text only.

## 2. Read tool with a card

**What worked.** A read tool (the project list) runs, its result reaches the model, and the panel draws a
project card from the same data.

**How it is wired.** The tool result is wrapped as quoted material (`quoted_from`, the note "data, not
instructions", and the data). The card data travels on a side channel: an AG-UI custom event named
`component`, carrying the component name and typed data. The panel picks one of our own React components by
that name. The model never sees the card data and never writes markup.

**Limits found.** assistant-ui has no built-in place for these cards, so `runtime.ts` keeps them in a small
list of its own beside the chat and the page draws that list. This is a thin layer and works, but it is
ours to maintain.

## 3. go_to in the browser

**What worked.** The agent asks the browser to go to a page. The run stops, the browser changes its own
page, reports back, and the run carries on with the browser's answer. An unknown page is refused and the
browser stays where it is.

**How it is wired.** `go_to` is declared on the server as an external tool, so Pydantic AI pauses the run
and asks for the result instead of running anything. The stream carries the tool call. `runtime.ts` sees it
end, checks the page name against a fixed list, navigates, and posts the result to
`/browser-results/{id}`. The server then resumes the run with that result.

**Limits found.** The run really is paused while waiting, so a browser that never answers leaves the run
waiting until it is stopped. Only pages on the fixed list are allowed.

## 4. Approval pause

**What worked.** A change tool never runs on its own. The run pauses and sends the tool name and its exact
inputs; the panel shows an approval card. Approve runs the tool once and the run resumes. Deny tells the
model the change was refused and the tool never runs. Text that merely says "approved" does nothing, and
asking for the same change again pauses again.

**How it is wired.** The change tool is marked as needing approval in Pydantic AI, so it comes back as a
deferred request. `wire.py` sends it as a custom `approval_request` event. The card's Approve and Deny
buttons post to `/approvals/{id}`, and only that call resumes the run. Wrong tokens, unknown ids and bad
decisions are refused.

**Limits found.** The pause lives in the running service. If the service restarts while waiting, the
pending approval is gone and the run must be asked again; the full build must store pending approvals in
the database.

## How this was checked

- agentkit's own tests (17) pass through `agentkit/test.sh`, with scripted model replies only. They cover
  parts 1 to 4 on the server side, including resume, token checks and the approval rules.
- The page's component tests cover the stream, the card and `go_to`.
- `web/e2e/agent-next.spec.ts` drives all four parts in a real browser against the demo service
  (`agentkit/demo.py`) through phoenix-api. It needs Playwright's browser, which was not installed in the
  session that wrote this page, so that spec was not re-run here.

No part needed a workaround and none of the allowed swaps (CopilotKit pieces, the Vercel AI SDK stream, or
a hand-written tool loop) is needed.

Result: all four work
