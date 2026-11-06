// "Discard work" on a failed or stopped build: deletes its worktree and branch (here and on GitHub) after a confirm.
// When the server says that would lose work (an open merge request, or commits main doesn't have) it refuses;
// the second dialog lists what would be lost and only then sends `force: true`.
import { useState } from "react"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { ApiError } from "@/lib/api"
import { useDiscardRun } from "@/lib/queries"
import type { RunDetail } from "@/lib/types"

const DISCARDABLE = ["failed", "stopped"]

/** The lines of work the server said a discard would lose, or null when the error was something else. */
function lostWork(error: unknown): string[] | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const body = error.body as { needs_force?: boolean; would_lose?: unknown } | null
  if (!body?.needs_force) return null
  return Array.isArray(body.would_lose) ? body.would_lose.map(String) : []
}

/** The Discard button (failed or stopped builds only), or "Work discarded" once it is done. */
export function DiscardControl({ name, run }: { name: string; run: RunDetail }) {
  const discard = useDiscardRun(name)
  const [confirming, setConfirming] = useState(false)
  const [lost, setLost] = useState<string[] | null>(null)
  if (run.discarded) return <p className="small" data-testid="discarded">Work discarded</p>
  if (!DISCARDABLE.includes(run.status)) return null
  const send = (force: boolean) =>
    discard.mutate({ runId: run.run_id, force }, {
      onError: (err) => setLost(force ? null : lostWork(err)),
      onSuccess: () => setLost(null),
    })
  const shownError = discard.error && lostWork(discard.error) === null ? discard.error.message : null
  return (
    <div className="stackg" style={{ gap: 8 }}>
      <Button variant="secondary" disabled={discard.isPending} onClick={() => setConfirming(true)}>
        {discard.isPending ? <Wheel /> : <Icon name="trash" />}
        Discard work
      </Button>
      {shownError && <Alert variant="destructive"><AlertDescription>{shownError}</AlertDescription></Alert>}
      <ConfirmDialog
        open={confirming} onOpenChange={setConfirming} title="Discard this build's work?"
        body={"Phoenix deletes the build's working folder and its branch, here and on GitHub. This can't be undone. "
          + "If the build still has an open merge request or work that's not on main, Phoenix stops and asks again first."}
        confirmLabel="Discard work" destructive
        onConfirm={() => send(false)}
      />
      <ConfirmDialog
        open={lost !== null} onOpenChange={(open) => { if (!open) setLost(null) }}
        title="This build has work that isn't on main"
        body={
          <div>
            <p>Discarding now throws this away for good:</p>
            <ul>{(lost ?? []).map((line) => <li key={line}>{line}</li>)}</ul>
            <p>Keep it if you might still want it; merge it first if it's good.</p>
          </div>
        }
        confirmLabel="Discard anyway and lose this work" destructive
        onConfirm={() => send(true)}
      />
    </div>
  )
}
