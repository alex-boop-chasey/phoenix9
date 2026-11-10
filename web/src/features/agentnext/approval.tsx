// The approval card, the go_to page move and the suggestion chips; all drawn from typed data, never from markup.
import { Button } from "@/components/ui/button"
import { findRoute, routeHash } from "@/lib/routes"
import type { ApprovalItem } from "./runtime"

/** One follow-up the agent offered: a message to send or a link to open. */
export interface Suggestion { label: string; message?: string; link?: string }

const TOOL_NAMES: Record<string, string> = { "notifications-set": "Change build notifications" }

function plainName(tool: string): string {
  return TOOL_NAMES[tool] ?? tool
}

function words(value: unknown): string {
  if (value === true) return "on"
  if (value === false) return "off"
  return typeof value === "string" ? value : JSON.stringify(value)
}

/** The lines saying exactly what will change, as label and value. */
function changeLines(item: ApprovalItem): { label: string; value: string }[] {
  const input = (item.input && typeof item.input === "object" ? item.input : {}) as Record<string, unknown>
  return Object.entries(input).map(([label, value]) => ({ label: label.replace(/_/g, " "), value: words(value) }))
}

/** A change waiting for Alex: what it will do, with Approve and Deny, then the decision. */
export function ApprovalCard({ item, onDecide }: { item: ApprovalItem; onDecide: (d: "approve" | "deny") => void }) {
  const input = (item.input ?? {}) as Record<string, unknown>
  const notify = item.toolName === "notifications-set" && typeof input.name === "string" && typeof input.on === "boolean"
  return (
    <section className="card" aria-label="Approval needed" data-testid="approval-card">
      <h3>The agent wants to make a change</h3>
      <p><strong>{plainName(item.toolName)}</strong></p>
      {notify ? (
        <p data-testid="approval-change">Build notifications for {String(input.name)}: {input.on ? "off → on" : "on → off"}</p>
      ) : (
        <dl data-testid="approval-change">
          {changeLines(item).map((l) => (
            <div key={l.label} className="flex gap-2"><dt>{l.label}:</dt><dd>{l.value}</dd></div>
          ))}
        </dl>
      )}
      {item.decision === "pending" ? (
        <div className="flex gap-2">
          <Button variant="primary" onClick={() => onDecide("approve")}>Approve</Button>
          <Button variant="secondary" onClick={() => onDecide("deny")}>Deny</Button>
        </div>
      ) : (
        <p>{item.decision === "approve" ? "Approved." : "Denied."}</p>
      )}
    </section>
  )
}

const REFUSED = { ok: false, error: "That page does not exist, so I did not go there." }

/** Build the go_to handler: moves to a known page and answers; refuses an unknown one. */
export function makeGoTo(navigate: (hash: string) => void) {
  return async (name: string, args: Record<string, unknown>): Promise<Record<string, unknown>> => {
    if (name !== "go_to") return { ok: false, error: "This page cannot do that." }
    const page = typeof args.page === "string" ? args.page : ""
    const params = (args.params ?? {}) as Record<string, unknown>
    if (!findRoute(page)) return REFUSED
    const hash = routeHash(page, params)
    if (!hash) return REFUSED
    navigate(hash.slice(1))
    return { ok: true, page }
  }
}

/** Whether a link may be shown: a dashboard hash, an https URL or a claude:// link. */
export function linkAllowed(link: string): boolean {
  if (link.startsWith("#/")) return true
  try {
    const u = new URL(link)
    return (u.protocol === "https:" && !!u.host) || (u.protocol === "claude:" && link.startsWith("claude://"))
  } catch {
    return false
  }
}

/** Keep only the chips that fit the shape and have an allowed kind of link. */
export function safeSuggestions(list: unknown): Suggestion[] {
  if (!Array.isArray(list)) return []
  const out: Suggestion[] = []
  for (const s of list) {
    if (!s || typeof s !== "object") continue
    const { label, message, link } = s as Record<string, unknown>
    if (typeof label !== "string" || !label) continue
    if (typeof message === "string" && link === undefined) out.push({ label, message })
    else if (typeof link === "string" && message === undefined && linkAllowed(link)) out.push({ label, link })
  }
  return out
}

/** Follow-up chips: a message chip sends its message; a link chip opens its link. */
export function SuggestionChips({ actions, onSend, onHash }: {
  actions: unknown; onSend: (message: string) => void; onHash?: (hash: string) => void
}) {
  const chips = safeSuggestions(actions)
  if (!chips.length) return null
  const open = (link: string) => {
    if (link.startsWith("#")) return onHash ? onHash(link.slice(1)) : void (window.location.hash = link)
    window.open(link, "_blank", "noopener,noreferrer")
  }
  return (
    <div className="flex flex-wrap gap-2" data-testid="suggestion-chips">
      {chips.map((c) => (
        <Button key={c.label} variant="secondary" onClick={() => (c.message !== undefined ? onSend(c.message) : open(c.link!))}>
          {c.label}
        </Button>
      ))}
    </div>
  )
}
