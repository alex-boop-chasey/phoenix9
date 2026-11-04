// Rules for the tool switches of an AI step: what each tool shows and what a switch writes.

/** A tool's state: allowed, denied, or following the step's defaults (no tools listed at all). */
export type ToolState = "on" | "off" | "default"

/** The `ai.tools` / `ai.tools_denied` pair of a step. */
export interface ToolLists {
  tools: string[]
  denied: string[]
}

/** True when the step lists no tools and denies none, so the step's own defaults apply. */
export const usesDefaults = ({ tools, denied }: ToolLists) => tools.length === 0 && denied.length === 0

/** What a switch shows for one tool: a denied tool is off; with an empty list nothing is restricted. */
export function toolState(lists: ToolLists, tool: string): ToolState {
  if (lists.denied.includes(tool)) return "off"
  if (lists.tools.length === 0) return "default"
  return lists.tools.includes(tool) ? "on" : "off"
}

/** The lists after switching one tool: turning on allows it (and un-denies it); turning off denies it and drops it from the allowed list. */
export function switchTool(lists: ToolLists, tool: string, on: boolean): ToolLists {
  const without = (l: string[]) => l.filter((t) => t !== tool)
  if (on) {
    return { tools: lists.tools.length === 0 || lists.tools.includes(tool) ? lists.tools : [...lists.tools, tool], denied: without(lists.denied) }
  }
  return { tools: without(lists.tools), denied: lists.denied.includes(tool) ? lists.denied : [...lists.denied, tool] }
}
