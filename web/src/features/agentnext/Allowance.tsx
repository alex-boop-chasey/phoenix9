// One short line above the message box when this month's allowance is low or used up; never a bar, never an amount.
import type { Allowance } from "./runtime"

const WORDS = {
  low: "The agent's allowance is getting low this month.",
  used_up: "The agent's allowance is used up this month.",
} as const

/** The allowance line: nothing while there is plenty left. */
export function AllowanceNote({ allowance }: { allowance: Allowance | null }) {
  if (!allowance || allowance.state === "plenty" || !(allowance.state in WORDS)) return null
  const used = allowance.state === "used_up"
  return (
    <p role="status" className={`ag-allow${used ? " used" : ""}`} data-testid="allowance">
      {WORDS[allowance.state]}
    </p>
  )
}
