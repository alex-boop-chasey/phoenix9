// "Discard work" on a failed or stopped build: deletes its worktree and branch (here and on GitHub) after a confirm.
import { useState } from "react"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { useDiscardRun } from "@/lib/queries"
import type { RunDetail } from "@/lib/types"

const DISCARDABLE = ["failed", "stopped"]

/** The Discard button (failed or stopped builds only), or "Work discarded" once it is done. */
export function DiscardControl({ name, run }: { name: string; run: RunDetail }) {
  const discard = useDiscardRun(name)
  const [confirming, setConfirming] = useState(false)
  if (run.discarded) return <p className="small" data-testid="discarded">Work discarded</p>
  if (!DISCARDABLE.includes(run.status)) return null
  return (
    <div className="stackg" style={{ gap: 8 }}>
      <Button variant="secondary" disabled={discard.isPending} onClick={() => setConfirming(true)}>
        {discard.isPending ? <Wheel /> : <Icon name="trash" />}
        Discard work
      </Button>
      {discard.error && <Alert variant="destructive"><AlertDescription>{discard.error.message}</AlertDescription></Alert>}
      <ConfirmDialog
        open={confirming} onOpenChange={setConfirming} title="Discard this build's work?"
        body="Phoenix deletes the build's working folder and its branch, here and on GitHub. This can't be undone."
        confirmLabel="Discard work" destructive
        onConfirm={() => discard.mutate(run.run_id)}
      />
    </div>
  )
}
