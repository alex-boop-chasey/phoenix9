// Small shared pieces of the agent's cards: the "Needs you" label and the success/failure marks.
import { Icon } from "@/components/Icon"

/** The class for a card: the plain card, or the orange-edged one while it waits for Alex. */
export function cardClass(waiting: boolean, extra = ""): string {
  return ["ag-card", waiting ? "needs-you" : "", extra].filter(Boolean).join(" ")
}

/** The quiet "Needs you" label in a waiting card's header. */
export function NeedsYou() {
  return <span className="ag-need" data-testid="needs-you">Needs you</span>
}

/** A small green check (ok) or red mark (not ok) beside plain words. */
export function Mark({ ok }: { ok: boolean }) {
  return ok ? <Icon name="check" size="sm" className="ag-ok" /> : <Icon name="x-circle" size="sm" className="ag-bad" />
}
