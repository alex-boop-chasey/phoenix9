// Types of the old Phoenix agent panel's data (shared by the web test fixtures).
export type AgentState = "asleep" | "idle" | "working" | "queued"

/** What the agent is doing now (`app_url` is present only when the Claude app can open it). */
export interface AgentStatus {
  state: AgentState
  pid: number | null
  session_id: string | null
  name: string
  app_url?: string
}

export type ActionStatus = "running" | "ok" | "error"

export interface UserItem { type: "user"; line: number; text: string; origin: string; at: string }
export interface AgentTextItem { type: "agent"; line: number; markdown: string; at: string }
export interface ActionItem {
  type: "action"; line: number; id: string; tool: string; title: string; input_summary: string
  status: ActionStatus; excerpt?: string; done_line?: number
}
export interface ThinkingItem { type: "thinking"; line: number; duration_s: number; at: string }
export interface QueuedItem { type: "queued"; line: number; text: string; pending: boolean; origin?: string; at: string }
export interface NoticeItem { type: "notice"; line: number; text: string }
export interface SessionItem { type: "session"; line: number; session_id: string }

export type AgentItem = UserItem | AgentTextItem | ActionItem | ThinkingItem | QueuedItem | NoticeItem | SessionItem

/** A stream `update` frame: an action already shown has finished. */
export interface AgentUpdate {
  type: "update"; id: string; line: number; status: ActionStatus; excerpt?: string
}

export interface AgentMessages {
  items: AgentItem[]
  unknown: number
  last_line: number
  session_id: string | null
}

export interface AgentSessionRow { session_id: string; started: string; lines: number }

export interface AgentContext { page?: string; project?: string; run?: string; suggestions?: number }
export interface AgentSendBody { text: string; context?: AgentContext }
export interface AgentSendResult { sent: boolean; at: string; after_line: number }
