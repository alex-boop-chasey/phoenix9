// The small footer under inline cards saying the content came from the agent.
/** The "proposed by the agent" footer line. */
export function InlineFooter({ text }: { text?: unknown }) {
  return <p className="muted text-xs" data-testid="card-footer">{typeof text === "string" && text ? text : "proposed by the agent"}</p>
}
