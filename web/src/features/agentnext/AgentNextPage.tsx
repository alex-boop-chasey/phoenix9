// The /agent-next page: the chat on assistant-ui, with our own cards, approval buttons and page moves.
import { AllowanceBar } from "./Allowance"
import { Conversation } from "./Conversation"
import { History } from "./History"
import { rememberThread, useThreads } from "./useThreads"

/** The agent's page: history and allowance beside one open conversation. */
export default function AgentNextPage() {
  const { threads, allowance, current, earlier, earlierCards, opened, follow, problem, refresh, open, fresh } = useThreads()

  if (problem) {
    return (
      <div data-testid="agent-next" className="flex flex-col gap-2">
        <h1>Agent</h1>
        <p role="alert">{problem}</p>
      </div>
    )
  }
  return (
    <div className="flex gap-4" data-testid="agent-next">
      <aside className="flex w-64 shrink-0 flex-col gap-4">
        <History threads={threads} current={current} onOpen={open} onNew={fresh} />
        <AllowanceBar allowance={allowance} />
      </aside>
      <div className="min-w-0 flex-1">
        <Conversation key={`${current}-${opened}`} thread={current} earlier={earlier} earlierCards={earlierCards} follow={follow} onRunEnd={refresh} onThread={rememberThread} />
      </div>
    </div>
  )
}
