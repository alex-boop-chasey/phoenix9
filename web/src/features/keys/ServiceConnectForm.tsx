// A small account-key form for one service: fixed key names, password fields, nothing echoed back.
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { post } from "@/lib/api"
import type { ConnectResult } from "@/lib/types"

/** One password field per account key name; values are cleared as soon as they are posted. */
export function ServiceConnectForm({
  endpoint, keyNames, onDone,
}: { endpoint: string; keyNames: string[]; onDone?: () => void }) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState("")
  const ready = keyNames.length > 0 && keyNames.every((n) => values[n])

  async function save() {
    setBusy(true)
    try {
      const sent = values
      setValues({})
      const result = await post<ConnectResult>(endpoint, { values: sent })
      setMessage(result.message)
      onDone?.()
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not connect the service.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="flex flex-col gap-2" onSubmit={(e) => { e.preventDefault(); void save() }}>
      {keyNames.map((n) => (
        <label key={n} className="flex flex-col gap-1 text-sm">
          <span className="font-mono text-xs">{n}</span>
          <Input
            type="password"
            autoComplete="off"
            aria-label={n}
            className="max-w-sm"
            value={values[n] ?? ""}
            onChange={(e) => setValues({ ...values, [n]: e.target.value })}
          />
        </label>
      ))}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={!ready || busy}>Save</Button>
        {message && <span role="status" className="text-sm">{message}</span>}
      </div>
    </form>
  )
}
