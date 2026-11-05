// The Configure dialog for one service: its account keys (saved ones are sealed), its settings, Test connection, Save.
import { useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"

import { Icon } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog"
import { post } from "@/lib/api"
import type { ConnectResult, ServiceStatus } from "@/lib/types"
import { serviceIcon } from "./serviceIcon"

type Test = { state: "idle" | "busy" | "ok" | "bad"; text: string }

/** The form body; mounted fresh each time the dialog opens so nothing typed lingers. */
function ConfigureForm({ service, onClose }: { service: ServiceStatus; onClose: () => void }) {
  const qc = useQueryClient()
  const name = service.title || service.name
  const [secrets, setSecrets] = useState<Record<string, string>>({})
  const [replacing, setReplacing] = useState<Record<string, boolean>>({})
  const [plain, setPlain] = useState<Record<string, string>>(
    Object.fromEntries((service.account_settings ?? []).map((s) => [s.name, s.value])),
  )
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [test, setTest] = useState<Test>({ state: "idle", text: "" })
  const endpoints = service.endpoints ?? {}
  const sealed = (k: string) => service.connected && !!service.ends_in?.[k] && !replacing[k]
  const missing = (service.account_keys ?? []).filter((k) => !sealed(k) && !secrets[k]?.trim())

  async function runTest() {
    if (!endpoints.test) return
    if (missing.length && !service.connected) {
      setError(`Paste the key first, then test.`)
      return
    }
    setError("")
    setTest({ state: "busy", text: "" })
    try {
      const sent = Object.fromEntries(Object.entries(secrets).filter(([, v]) => v))
      const r = await post<{ ok: boolean; message: string }>(endpoints.test, { values: sent })
      setTest({ state: r.ok ? "ok" : "bad", text: r.message })
    } catch (e) {
      setTest({ state: "bad", text: e instanceof Error ? e.message : "The test did not run." })
    }
  }

  async function save() {
    if (!endpoints.connect) return
    if (missing.length && !service.connected) {
      setError(`Paste ${missing[0]} to connect.`)
      return
    }
    setError("")
    setBusy(true)
    try {
      const sent = Object.fromEntries(Object.entries(secrets).filter(([, v]) => v.trim()))
      const r = await post<ConnectResult>(endpoints.connect, { values: sent, settings: plain })
      toast.success(service.connected ? `${name} settings saved.` : `${name} connected.`, { description: r.message })
      void qc.invalidateQueries({ queryKey: ["global-services"] })
      void qc.invalidateQueries({ queryKey: ["services"] })
      void qc.invalidateQueries({ queryKey: ["keys-audit"] })
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); void save() }}>
      <div className="cfgform">
        {(service.account_keys ?? []).map((k) => (
          <div className="field" key={k}>
            {sealed(k) ? (
              <>
                <span className="lbl mono">{k}</span>
                <div className="sealed">
                  <Icon name="lock-key" size="sm" />
                  <span>Saved, ends in <span className="mono">{service.ends_in?.[k]}</span></span>
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setReplacing({ ...replacing, [k]: true })}>Replace</button>
                </div>
                <span className="help">The value is never shown again.</span>
              </>
            ) : (
              <>
                <label className="mono" htmlFor={`cf-${k}`}>{k}</label>
                <input
                  id={`cf-${k}`} className="input mono" type="password" autoComplete="off"
                  placeholder={service.connected ? "Paste the new key" : "Paste the key"}
                  value={secrets[k] ?? ""} onChange={(e) => setSecrets({ ...secrets, [k]: e.target.value })}
                />
                <span className="help">Sealed when saved; the value is never shown again.</span>
              </>
            )}
          </div>
        ))}
        {(service.account_settings ?? []).map((s) => (
          <div className="field" key={s.name}>
            <label htmlFor={`cs-${s.name}`}>{s.label}</label>
            {s.kind === "select" ? (
              <select id={`cs-${s.name}`} className="select" value={plain[s.name] ?? ""} onChange={(e) => setPlain({ ...plain, [s.name]: e.target.value })}>
                {s.options.map((o) => <option key={o}>{o}</option>)}
              </select>
            ) : (
              <input id={`cs-${s.name}`} className="input" value={plain[s.name] ?? ""} placeholder={s.placeholder}
                onChange={(e) => setPlain({ ...plain, [s.name]: e.target.value })} />
            )}
            {s.help && <span className="help">{s.help}</span>}
          </div>
        ))}
        {service.name === "supabase" && (
          <div className="blk-info"><Icon name="info" /><span>Each project's own Supabase address and anon key go in that project's Settings.</span></div>
        )}
      </div>
      {error && <p className="cfgerr" role="alert"><Icon name="warning-circle" size="sm" />{error}</p>}
      {test.state !== "idle" && test.state !== "busy" && (
        <p className={test.state === "ok" ? "light ok" : "cfgerr"} role="status">{test.text}</p>
      )}
      <DialogFooter className="dlg-f">
        {service.can_test && endpoints.test && (
          <button type="button" className="btn btn-ghost" style={{ marginRight: "auto" }} disabled={test.state === "busy"} onClick={() => void runTest()}>
            {test.state === "busy" ? <><Wheel />Testing…</> : <><Icon name="plugs-connected" />Test connection</>}
          </button>
        )}
        <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
        <button type="submit" className="btn btn-primary" disabled={busy}>{service.connected ? "Save" : "Save and connect"}</button>
      </DialogFooter>
    </form>
  )
}

/** The dialog around the form; `service` null means closed. */
export function ConfigureDialog({ service, onClose }: { service: ServiceStatus | null; onClose: () => void }) {
  return (
    <Dialog open={service !== null} onOpenChange={(o) => { if (!o) onClose() }}>
      <DialogContent className="cfgdlg">
        {service && (
          <>
            <div className="dlg-h">
              <span className="ico"><Icon name={serviceIcon(service.name)} size="lg" /></span>
              <DialogTitle>Configure {service.title || service.name}</DialogTitle>
            </div>
            <DialogDescription>{service.description}</DialogDescription>
            <ConfigureForm key={service.name} service={service} onClose={onClose} />
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
