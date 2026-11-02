// A group of separate outlined radio options (no connecting line), used for every wizard choice.
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export interface ChoiceOption {
  value: string
  label: string
  help?: ReactNode
  icon?: ReactNode
  disabled?: boolean
}

/** Outlined radio options; the radio's name is the option's label. */
export function Choices({ name, label, value, options, onChange, disabled = false }: {
  name: string
  label: string
  value: string
  options: ChoiceOption[]
  onChange: (value: string) => void
  disabled?: boolean
}) {
  return (
    <div className="rail choices" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <label key={o.value} className={cn("rrow", (disabled || o.disabled) && "locked")}>
          <input
            type="radio" name={name} value={o.value} aria-label={o.label} checked={value === o.value}
            disabled={disabled || o.disabled} onChange={() => onChange(o.value)}
          />
          <span className="node" />
          <span className="rt">
            <b>{o.icon}{o.label}</b>
            {o.help && <small>{o.help}</small>}
          </span>
        </label>
      ))}
    </div>
  )
}

/** An outlined row with a switch on the right (tools, merge extras). */
export function SwitchRow({ id, label, help, checked, disabled, onChange }: {
  id: string; label: string; help?: string; checked: boolean; disabled?: boolean; onChange: (on: boolean) => void
}) {
  return (
    <label className="rrow nodot" htmlFor={id}>
      <span className="rt"><b>{label}</b>{help && <small>{help}</small>}</span>
      <input
        id={id} type="checkbox" role="switch" className="switch" aria-label={label}
        checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)}
      />
    </label>
  )
}
