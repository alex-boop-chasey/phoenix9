// The keys table: Name, Value, Secret rows with Save and Add (used on New project and in Settings).
import { useEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { Icon } from "@/components/Icon"
import { ConfirmDialog } from "@/components/ConfirmDialog"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"
import { keys, useKeyRows, useLibraryServices } from "@/lib/queries"
import type { KeyInput, KeyRow } from "@/lib/types"

const NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/
const DOTS = "••••••"

interface Row {
  id: number
  name: string
  value: string
  secret: boolean
  saved: boolean
  hasValue: boolean
  edited: boolean
  revealed: boolean
  /** The service that added this draft row (cleared once the row is kept on its own). */
  service?: string
  /** The service's one-line help for this key, and whether it can be left out. */
  help?: string
  optional?: boolean
}

/** A key a ticked service asks for. */
export interface WantedKey {
  service: string
  name: string
  secret: boolean
  required?: boolean
  help?: string
}

/** How many key rows there are and how many still need a value. */
export interface RowsSummary {
  total: number
  needValue: number
}

let nextId = 1
const blankRow = (): Row => ({
  id: nextId++, name: "", value: "", secret: true, saved: false, hasValue: false, edited: false, revealed: false,
})

function fromServer(r: KeyRow): Row {
  return {
    id: nextId++, name: r.name, value: r.secret ? "" : (r.value_if_not_secret ?? ""), secret: r.secret,
    saved: true, hasValue: r.has_value, edited: false, revealed: false,
  }
}

const isBlank = (r: Row) => !r.saved && !r.name.trim() && !r.value
const isPlaceholder = (r: Row) => !r.saved && !!r.service && !r.value
const isDots = (r: Row) => r.saved && r.secret && r.hasValue && !r.edited && !r.revealed
const keepsSavedValue = (r: Row) => r.saved && r.secret && r.hasValue && !r.edited

/** Check the rows; returns a message per row id (empty when all is fine). */
export function validateKeyRows(rows: Row[], mode: "local" | "saved" = "saved"): Record<number, string> {
  const errors: Record<number, string> = {}
  const seen = new Set<string>()
  for (const r of rows.filter((x) => !isBlank(x))) {
    const name = r.name.trim()
    if (!name) errors[r.id] = "Type a name for this key, or remove the row."
    else if (!NAME_RE.test(name)) errors[r.id] = `"${name}" is not a good name: use letters, digits and underscores, and do not start with a digit.`
    else if (seen.has(name)) errors[r.id] = `There are two keys named ${name}.`
    else if (/[\r\n]/.test(r.value)) errors[r.id] = "The value cannot have line breaks."
    else if (!(keepsSavedValue(r) && (mode === "saved")) && !r.value) errors[r.id] = `Type a value for ${name}.`
    seen.add(name)
  }
  return errors
}

function toInput(r: Row, local = false): KeyInput {
  const name = r.name.trim()
  return keepsSavedValue(r) && !local ? { name, secret: r.secret } : { name, value: r.value, secret: r.secret }
}

/** Key rows with Save and Add. `saved` talks to the project's keys; `local` keeps rows in memory. */
export function KeysForm({
  mode, project = "", draft = false, onRowsChange, wanted,
}: {
  mode: "local" | "saved"
  project?: string
  /** The New project look: dashed rows until saved, plus a note under the buttons. */
  draft?: boolean
  /** Local mode: the saved rows (to send with create) and whether typed rows are still unsaved. */
  onRowsChange?: (rows: KeyInput[], pending: boolean, summary: RowsSummary) => void
  /** Local mode: keys the ticked services ask for; draft rows are added and removed to match. */
  wanted?: WantedKey[]
}) {
  const qc = useQueryClient()
  const query = useKeyRows(mode === "saved" ? project : "")
  const library = useLibraryServices(mode === "saved")
  const usedFor = (name: string) => library.data?.services.find((s) => s.project_keys.some((k) => k.name === name))?.title
  const [rows, setRows] = useState<Row[]>(() => (mode === "local" && draft ? [] : [blankRow()]))
  const [errors, setErrors] = useState<Record<number, string>>({})
  const [problem, setProblem] = useState("")
  const [busy, setBusy] = useState(false)
  const [removing, setRemoving] = useState<Row | null>(null)
  const [kept, setKept] = useState<string[]>([])
  const loaded = useRef(false)
  const rowsRef = useRef(rows)
  rowsRef.current = rows

  useEffect(() => {
    if (mode === "saved" && query.data && !loaded.current) {
      loaded.current = true
      setRows([...query.data.map(fromServer), blankRow()])
    }
  }, [mode, query.data])

  useEffect(() => {
    if (mode !== "local") return
    const pending = rows.some((r) => !isBlank(r) && !r.saved && !isPlaceholder(r))
    const real = rows.filter((r) => !isBlank(r))
    const summary = { total: real.length, needValue: real.filter((r) => !r.value).length }
    onRowsChange?.(rows.filter((r) => r.saved).map((r) => toInput(r, true)), pending, summary)
  }, [mode, rows, onRowsChange])

  // Keep the draft rows in step with the ticked services.
  useEffect(() => {
    if (mode !== "local" || !wanted) return
    const current = rowsRef.current
    const names = new Set(wanted.map((w) => w.service))
    const gone = current.filter((r) => r.service && !names.has(r.service))
    const added = wanted.filter((w) => !current.some((r) => r.name.trim() === w.name))
    const keptNames = gone.filter((r) => r.value).map((r) => r.name)
    setKept(keptNames)
    if (!gone.length && !added.length) return
    setRows((rs) => {
      const rest = rs
        .filter((r) => !(r.service && !names.has(r.service) && !r.value))
        .map((r) => (r.service && !names.has(r.service) ? { ...r, service: undefined } : r))
      const fresh = added.map((w) => ({
        ...blankRow(), name: w.name, secret: w.secret, service: w.service, help: w.help, optional: w.required === false,
      }))
      return [...rest, ...fresh]
    })
  }, [mode, wanted])

  const change = (id: number, patch: Partial<Row>) => {
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...patch } : r)))
    setErrors((e) => {
      const { [id]: _gone, ...rest } = e
      return rest
    })
  }

  const edit = (r: Row, patch: Partial<Row>) => change(r.id, { ...patch, edited: true })

  /** Validate, then save (or lock in local mode). Returns the new rows, or null when refused. */
  async function save(): Promise<Row[] | null> {
    const checked = rows.filter((r) => !isPlaceholder(r))
    const found = validateKeyRows(checked, mode)
    setErrors(found)
    setProblem("")
    if (Object.keys(found).length) return null
    const real = checked.filter((r) => !isBlank(r))
    if (mode === "local") {
      const locked = real.map((r) => ({ ...r, name: r.name.trim(), saved: true, hasValue: true, edited: false, revealed: false }))
      const all = rows.filter(isPlaceholder).length ? [...locked, ...rows.filter(isPlaceholder)] : locked
      setRows(all)
      return all
    }
    if (!real.length) return rows
    setBusy(true)
    try {
      const saved = await api.saveKeys(project, real.map((r) => toInput(r)))
      qc.setQueryData(keys.keyRows(project), saved)
      const fresh = saved.map(fromServer)
      setRows(fresh)
      toast.success("Keys saved")
      return fresh
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "Could not save the keys.")
      return null
    } finally {
      setBusy(false)
    }
  }

  async function saveOnly() {
    const hadBlank = rows.some(isBlank)
    const done = await save()
    if (done && hadBlank && !done.some(isBlank)) setRows([...done, blankRow()])
  }

  async function add() {
    const done = await save()
    if (done) setRows([...done, blankRow()])
  }

  async function reveal(r: Row) {
    if (mode === "local") return change(r.id, { revealed: true })
    try {
      const got = await api.revealKey(project, r.name)
      change(r.id, { revealed: true, value: got.value })
    } catch (err) {
      setProblem(err instanceof Error ? err.message : "Could not reveal the key.")
    }
  }

  const hide = (r: Row) => change(r.id, { revealed: false, value: mode === "local" ? r.value : "" })

  async function remove(r: Row) {
    if (mode === "saved") {
      try {
        const left = await api.removeKey(project, r.name)
        qc.setQueryData(keys.keyRows(project), left)
      } catch (err) {
        setProblem(err instanceof Error ? err.message : "Could not remove the key.")
        return
      }
    }
    setRows((rs) => {
      const rest = rs.filter((x) => x.id !== r.id)
      return rest.length || draft ? rest : [blankRow()]
    })
  }

  if (mode === "saved" && query.isLoading) return <p className="text-sm text-muted-foreground">Loading keys…</p>

  return (
    <div className="space-y-3">
      {problem && (
        <Alert variant="destructive"><AlertDescription>{problem}</AlertDescription></Alert>
      )}
      {draft ? (
        <ul className="stackg">
          {rows.length === 0 && <li className="small">No keys yet. Pick a service above, or press Add.</li>}
          {rows.map((r) => (
            <KeyRowView
              key={r.id} row={r} error={errors[r.id]}
              onName={(name) => edit(r, { name })}
              onValue={(value) => edit(r, { value })}
              onSecret={(secret) => edit(r, { secret })}
              onReveal={() => void reveal(r)} onHide={() => hide(r)} onRemove={() => setRemoving(r)}
            />
          ))}
        </ul>
      ) : (
        <div className="tscroll">
          <table className="keys">
            <thead>
              <tr><th>Name</th><th>Value</th><th>Kind</th><th>Used for</th><th><span className="sr">Actions</span></th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <KeyTableRow
                  key={r.id} row={r} error={errors[r.id]} usedFor={usedFor(r.name.trim())}
                  onName={(name) => edit(r, { name })}
                  onValue={(value) => edit(r, { value })}
                  onSecret={(secret) => edit(r, { secret })}
                  onReveal={() => void reveal(r)} onHide={() => hide(r)} onRemove={() => setRemoving(r)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="row">
        <Button type="button" variant="secondary" size="sm" disabled={busy} onClick={() => void saveOnly()}>
          Save
        </Button>
        <Button type="button" variant="secondary" size="sm" disabled={busy} onClick={() => void add()}>
          <Icon name="plus" />Add
        </Button>
      </div>
      {kept.length > 0 && (
        <p className="small" role="status">
          Kept {kept.join(", ")} because you typed a value. Remove {kept.length === 1 ? "it" : "them"} yourself if not needed.
        </p>
      )}
      {draft && (
        <div className="blk-info">
          <Icon name="info" />
          <span>Dashed rows are not saved yet. Rows are kept here until you press Create project.</span>
        </div>
      )}
      <ConfirmDialog
        open={removing !== null} onOpenChange={(open) => !open && setRemoving(null)}
        title={`Remove key ${removing?.name ?? ""}?`} body="The saved value will be deleted."
        confirmLabel="Remove" destructive
        onConfirm={() => { if (removing) void remove(removing); setRemoving(null) }}
      />
    </div>
  )
}

function KeyRowView({
  row, error, onName, onValue, onSecret, onReveal, onHide, onRemove,
}: {
  row: Row
  error?: string
  onName: (v: string) => void
  onValue: (v: string) => void
  onSecret: (v: boolean) => void
  onReveal: () => void
  onHide: () => void
  onRemove: () => void
}) {
  const dots = isDots(row)
  const needsValue = row.saved && !row.hasValue && !row.value
  return (
    <li className="space-y-1">
      <div className={`krow${row.saved ? " saved" : ""}`}>
        <div className="row" style={{ gap: 6, flexWrap: "nowrap", minWidth: 0 }}>
          <Input
            aria-label="Name" placeholder="NAME" value={row.name} readOnly={row.saved} autoComplete="off"
            aria-invalid={!!error} onChange={(e) => onName(e.target.value)}
          />
          {row.optional && <span className="tag">Optional</span>}
        </div>
        <Input
          aria-label="Value" autoComplete="off" aria-invalid={!!error}
          type={row.secret && !row.revealed && !dots ? "password" : "text"}
          value={dots ? DOTS : row.value} readOnly={dots}
          placeholder={needsValue ? "Needs a value" : "value"}
          onChange={(e) => onValue(e.target.value)}
        />
        <label className="flex items-center gap-2 text-sm">
          <Checkbox
            aria-label="Secret" checked={row.secret} disabled={dots}
            onCheckedChange={(v) => onSecret(v === true)}
          />
          Secret
        </label>
        <div className="flex gap-2">
          {row.saved && row.secret && row.hasValue && (
            row.revealed
              ? <Button type="button" size="sm" variant="outline" onClick={onHide}>Hide</Button>
              : <Button type="button" size="sm" variant="outline" onClick={onReveal}>Reveal</Button>
          )}
          {row.saved && <Button type="button" size="sm" variant="outline" onClick={onRemove}>Remove</Button>}
        </div>
      </div>
      {row.help && <p className="help">{row.help}</p>}
      {needsValue && !error && <p className="text-xs text-muted-foreground">Needs a value</p>}
      {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
    </li>
  )
}

/** One key as a table row: name, value, kind, what it is used for, and Reveal / Remove. */
function KeyTableRow({
  row, error, usedFor, onName, onValue, onSecret, onReveal, onHide, onRemove,
}: {
  row: Row
  error?: string
  usedFor?: string
  onName: (v: string) => void
  onValue: (v: string) => void
  onSecret: (v: boolean) => void
  onReveal: () => void
  onHide: () => void
  onRemove: () => void
}) {
  const dots = isDots(row)
  const needsValue = row.saved && !row.hasValue && !row.value
  return (
    <>
      <tr>
        <td>
          <Input
            aria-label="Name" placeholder="NAME" value={row.name} readOnly={row.saved} autoComplete="off"
            className="mono" aria-invalid={!!error} onChange={(e) => onName(e.target.value)}
          />
        </td>
        <td>
          <Input
            aria-label="Value" autoComplete="off" aria-invalid={!!error} className="mono"
            type={row.secret && !row.revealed && !dots ? "password" : "text"}
            value={dots ? DOTS : row.value} readOnly={dots}
            placeholder={needsValue ? "Needs a value" : "value"}
            onChange={(e) => onValue(e.target.value)}
          />
        </td>
        <td>
          <label className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
            <Checkbox aria-label="Secret" checked={row.secret} disabled={dots} onCheckedChange={(v) => onSecret(v === true)} />
            <span className="tag">{row.secret && <Icon name="lock" />}{row.secret ? "Secret" : "Public"}</span>
          </label>
        </td>
        <td>{usedFor ? <span className="chip">{usedFor}</span> : "—"}</td>
        <td>
          <div className="row" style={{ gap: 2, flexWrap: "nowrap" }}>
            {row.saved && row.secret && row.hasValue && (
              <button type="button" className="btn btn-ghost btn-icon btn-sm" aria-label={row.revealed ? "Hide" : "Reveal"} onClick={row.revealed ? onHide : onReveal}>
                <Icon name={row.revealed ? "eye-slash" : "eye"} />
              </button>
            )}
            {row.saved && (
              <button type="button" className="btn btn-ghost btn-icon btn-sm" aria-label="Remove key" onClick={onRemove}>
                <Icon name="trash" />
              </button>
            )}
          </div>
        </td>
      </tr>
      {(error || needsValue) && (
        <tr>
          <td colSpan={5} style={{ paddingTop: 0 }}>
            {error ? <p className="text-sm text-destructive" role="alert">{error}</p> : <p className="help">Needs a value</p>}
          </td>
        </tr>
      )}
    </>
  )
}
