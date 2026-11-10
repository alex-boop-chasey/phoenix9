// A thin bar and a few words showing how much of this month's allowance is used; never an amount.
import type { Allowance } from "./runtime"

const WORDS = { plenty: "plenty left this month", low: "getting low", used_up: "used up this month" } as const

/** The allowance indicator. */
export function AllowanceBar({ allowance }: { allowance: Allowance | null }) {
  if (!allowance) return null
  const percent = Math.round(Math.min(1, Math.max(0, allowance.used_share)) * 100)
  return (
    <div className="flex flex-col gap-1" data-testid="allowance">
      <div className="h-1.5 w-full rounded-full bg-muted" role="presentation">
        <div
          className={`h-full rounded-full ${allowance.state === "plenty" ? "bg-primary" : "bg-destructive"}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="text-xs text-muted-foreground">{WORDS[allowance.state]}</p>
    </div>
  )
}
