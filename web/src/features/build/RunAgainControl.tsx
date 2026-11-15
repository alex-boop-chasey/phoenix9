// "Run again" on a failed or stopped build: after a confirm (with the preset, normally left as it was) Phoenix
// starts a new build from the same spec, reference documents and settings, and the page moves to it.
// A refusal from the server stays in the dialog so Alex can read it and pick another preset or cancel.
import { useState } from "react"
import { useNavigate } from "react-router"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { Button } from "@/components/ui/button"
import { useLibraryPresets, useRunAgain } from "@/lib/queries"
import type { RunDetail } from "@/lib/types"

const REPEATABLE = ["failed", "stopped"]

/** The preset choice inside the dialog (loads the library's presets only once the dialog is open). */
function PresetPick({ own, value, onChange }: { own: string; value: string; onChange: (v: string) => void }) {
  const presets = useLibraryPresets()
  const rows = (presets.data?.presets ?? []).filter((p) => p.name !== "custom" || own === "custom")
  const names = rows.map((p) => p.name)
  const options = names.includes(own) ? rows : [{ name: own, title: own === "custom" ? "Custom" : own }, ...rows]
  return (
    <div className="stackg" style={{ gap: 8, marginTop: 16 }}>
      <label htmlFor="run-again-preset" className="small">Preset</label>
      <select id="run-again-preset" className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((p) => <option key={p.name} value={p.name}>{p.title}</option>)}
      </select>
      <p className="small">Change it only if you want this build to run differently.</p>
    </div>
  )
}

/** The Run again button (failed or stopped builds only) and its confirm dialog. */
export function RunAgainControl({ name, run }: { name: string; run: RunDetail }) {
  const again = useRunAgain(name)
  const navigate = useNavigate()
  const [confirming, setConfirming] = useState(false)
  const [preset, setPreset] = useState(run.preset)
  if (!REPEATABLE.includes(run.status)) return null
  const open = (next: boolean) => {
    if (again.isPending) return
    if (next) { setPreset(run.preset); again.reset() }
    setConfirming(next)
  }
  const send = () => {
    if (again.isPending) return
    const changed = preset !== run.preset ? preset : undefined
    again.mutate({ runId: run.run_id, preset: changed }, {
      onSuccess: (res) => {
        setConfirming(false)
        void navigate(`/p/${encodeURIComponent(name)}/build?run=${encodeURIComponent(res.run_id)}`,
          { replace: true, state: { started: true } })
      },
    })
  }
  return (
    <>
      <Button disabled={again.isPending} onClick={() => open(true)}>
        {again.isPending ? <Wheel /> : <Icon name="arrow-counter-clockwise" />}
        Run again
      </Button>
      <ConfirmDialog
        open={confirming} onOpenChange={open} title="Run this build again?"
        body={
          <div>
            <p>Phoenix starts a new build from the same spec, reference documents and settings. This build stays as it is.</p>
            {confirming && <PresetPick own={run.preset} value={preset} onChange={setPreset} />}
          </div>
        }
        confirmLabel="Run again" stayOpen pending={again.isPending} error={again.error?.message ?? null}
        onConfirm={send}
      />
    </>
  )
}
