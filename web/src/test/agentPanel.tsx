// Render the agent panel full screen, as `#/agent-next` opens it, for the agent's behaviour tests.
import { AgentDrawer } from "@/features/agentnext/AgentDrawer"
import { renderWithProviders } from "@/test/render"

/** The open agent panel in its full-screen size at `route`, inside a query client and an in-memory router. */
export function renderFullAgent(route = "/agent-next") {
  return renderWithProviders(<AgentDrawer open size="full" onSize={() => {}} onClose={() => {}} opener={{ current: null }} />, { route })
}
