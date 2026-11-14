// What page Alex is on, as the small context the Phoenix agent is told about, and what has been sent already.
import type { AgentContext } from "@/features/agent/useAgent"

export { readPageContext, type PageContext } from "@/features/agentnext/pageContext"

/** The parts of `now` that differ from what the agent was last told (nothing when equal). */
export function changedParts(now: AgentContext, told: AgentContext | undefined): AgentContext {
  const out: AgentContext = {}
  for (const key of ["page", "project", "run"] as const) {
    if (now[key] && now[key] !== told?.[key]) out[key] = now[key]
  }
  return out
}

/** The exact line the server will build from these parts (mirrors the server's panel envelope). */
export function contextLine(parts: AgentContext): string {
  const bits: string[] = []
  if (parts.page) bits.push(`page: ${parts.page}`)
  if (parts.project) bits.push(`project: ${parts.project}`)
  if (parts.project) bits.push(`folder: /srv/projects/${parts.project}`)
  else if (parts.page || parts.run) bits.push("folder: Phoenix")
  if (parts.run) bits.push(`run: ${parts.run}`)
  return bits.length ? `[Phoenix panel · ${bits.join(" · ")}]` : ""
}

const told = new Map<string, AgentContext>()

/** What the agent was last told in this conversation. */
export const toldFor = (session: string) => told.get(session)
/** Remember what the agent now knows in this conversation. */
export const rememberTold = (session: string, now: AgentContext) => void told.set(session, { ...now })
/** Forget everything remembered (tests). */
export const forgetTold = () => told.clear()
