// The "Primary model" and "Backup model" dropdowns shared by the wizard card and project Settings.
import { useId } from "react"

/** Models offered when the presets name none. */
const KNOWN_MODELS = ["claude-opus-5-5", "claude-fable-5-1", "claude-sonnet-5-5"]

/** The model choices: the known ones plus anything the presets or this step already use. */
export function modelChoices(...used: (string | undefined)[][]): string[] {
  return [...new Set([...KNOWN_MODELS, ...used.flat().filter((m): m is string => !!m)])]
}

/** Two matching full-width dropdowns; the backup is optional and only the first backup is shown (the rest are kept). */
export function ModelPicker({ model, backups, models, disabled = false, onModel, onBackups }: {
  model: string
  backups: string[]
  models: string[]
  disabled?: boolean
  onModel: (model: string) => void
  onBackups: (backups: string[]) => void
}) {
  const uid = useId()
  const choices = modelChoices([model], backups, models)
  const first = backups[0] ?? ""
  return (
    <div className="mpick">
      <div className="field">
        <label htmlFor={`${uid}-primary`}>Primary model</label>
        <select id={`${uid}-primary`} className="select mono" disabled={disabled} value={model} onChange={(e) => onModel(e.target.value)}>
          {!model && <option value="">Default model</option>}
          {choices.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      </div>
      <div className="field">
        <label htmlFor={`${uid}-backup`}>Backup model (optional)</label>
        <select
          id={`${uid}-backup`} className="select mono" disabled={disabled} value={first}
          onChange={(e) => onBackups(e.target.value ? [e.target.value, ...backups.slice(1)] : backups.slice(1))}
        >
          <option value="">None</option>
          {choices.filter((m) => m !== model || m === first).map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <span className="help">Used if the primary model is unavailable.</span>
      </div>
    </div>
  )
}
