// Body of the repair card: the run's summary, the proposed repair note with its dry run, and Apply / Edit.
import { useState } from "react"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { post } from "@/lib/api"

import type { CardBodyProps } from "../cardBodies"

interface DryRun {
  error?: string
  ok?: boolean
  steps?: string[]
  refused?: string | null
  check_after?: string[] | null
  would_roll_back?: boolean
}
interface RepairData {
  run_id: string
  status_line: string
  findings: { code: string; text: string; task: number | null }[]
  note: { name: string; text: string; dry_run: DryRun | null } | null
}

/** True when the note has a step that throws locked checks away (it needs the unlock approval). */
function unlocksChecks(note: string | null): boolean {
  return (note ?? "").split("\n").some((line) => /^- rewrite the checks of task \d+ because \S/.test(line.trim()))
}

function errorText(err: unknown): string {
  return err instanceof Error && err.message ? err.message : "it did not work"
}

/** One plain line about a dry run. */
function dryText(d: DryRun): string {
  if (d.error) return `The note cannot be used: ${d.error}`
  if (d.refused) return `A step was refused: ${d.refused}`
  if (d.would_roll_back) return "The check would fail after these steps, so they would be rolled back."
  return "The dry run went fine: the check passes after these steps."
}

/** The summary, note and buttons of a repair card; read-only when the card is frozen. */
export function RepairBody({ data, frozen = false }: CardBodyProps) {
  const card = data as RepairData | null
  const [text, setText] = useState<string | null>(card?.note?.text ?? null)
  const [dry, setDry] = useState<DryRun | null>(card?.note?.dry_run ?? null)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState("")
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)
  if (!card || typeof card !== "object" || !card.run_id) return <p className="muted">No repair information.</p>
  const path = `repair/${encodeURIComponent(card.run_id)}/apply`

  async function save() {
    setBusy(true)
    try {
      const out = await post<DryRun>(path, { note: draft, dry_run: true })
      setText(draft)
      setDry(out)
      setEditing(false)
      setMessage(null)
    } catch (err) {
      setDry({ error: errorText(err) })
      setText(draft)
      setEditing(false)
    } finally {
      setBusy(false)
    }
  }

  async function apply() {
    setConfirm(false)
    setBusy(true)
    try {
      const body = unlocksChecks(text) ? { note: text, confirm: true, approve_unlock: true } : { note: text, confirm: true }
      const out = await post<{ ok?: boolean; rolled_back?: boolean }>(path, body)
      setMessage(out.rolled_back ? { ok: false, text: "The check failed, so the repair was rolled back." } : { ok: true, text: "Repair applied." })
    } catch (err) {
      setMessage({ ok: false, text: `Apply failed: ${errorText(err)}` })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-2" data-testid="card-repair">
      <p className="m-0" data-testid="repair-status">{card.status_line}</p>
      {card.findings.length > 0 && (
        <ul className="m-0 pl-5" data-testid="repair-findings">
          {card.findings.map((f, i) => <li key={i}>{f.text}</li>)}
        </ul>
      )}
      {text === null ? <p className="muted" data-testid="repair-no-note">No repair note yet.</p> : editing ? (
        <Textarea aria-label="Repair note" className="mono" rows={10} value={draft} onChange={(e) => setDraft(e.target.value)} />
      ) : (
        <pre className="ag-code mono" data-testid="repair-note"><code>{text}</code></pre>
      )}
      {dry && !editing && <p className="m-0" data-testid="repair-dry">{dryText(dry)}</p>}
      {message && <p className={message.ok ? "m-0" : "m-0 text-destructive"} role="status" data-testid="repair-result">{message.text}</p>}
      {!frozen && text !== null && (
        <div className="flex flex-wrap gap-2">
          {editing ? (
            <>
              <Button type="button" size="sm" disabled={busy} onClick={() => void save()}>Save</Button>
              <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => setEditing(false)}>Cancel</Button>
            </>
          ) : (
            <>
              <Button type="button" size="sm" disabled={busy} onClick={() => setConfirm(true)}>Apply</Button>
              <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => { setDraft(text); setEditing(true) }}>Edit</Button>
            </>
          )}
        </div>
      )}
      <ConfirmDialog open={confirm} onOpenChange={setConfirm} title="Apply this repair?"
        body={(unlocksChecks(text)
          ? "This note unlocks the task's locked checks: they are thrown away and written again. "
          : "") + "Phoenix takes a snapshot, applies the note and checks the run. If the check fails it rolls back."}
        confirmLabel="Apply" onConfirm={() => void apply()} />
    </div>
  )
}
