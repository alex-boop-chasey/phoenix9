import { askerText, unlockWord } from "@/features/gates/repairUnlock"
import type { Gate } from "@/lib/types"

/** What a repair-unlock question asks: the run, the repairs in plain words and the agent's reason. */
export function RepairUnlockBody({ gate }: { gate: Gate }) {
  const steps = gate.unlock_steps ?? []
  return (
    <div className="flex flex-col gap-1 text-sm" data-testid="repair-unlock">
      <p>{askerText(gate)} asks you to allow, once, a repair it may not do alone on build <b className="mono">{gate.run}</b>:</p>
      <ul className="list-disc pl-5" aria-label="Repairs asked for">
        {steps.map((s) => <li key={s}>{unlockWord(s)}</li>)}
      </ul>
      {gate.why && <p><b>Why:</b> {gate.why}</p>}
      <p className="text-muted-foreground">"Allow once" lets it do exactly these repairs on this build, one time, within 30 minutes.</p>
    </div>
  )
}
