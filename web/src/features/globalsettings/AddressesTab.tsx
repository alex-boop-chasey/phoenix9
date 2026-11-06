// Phoenix settings > Dashboard addresses: where the dashboard lives, the page addresses allowed to change things, and VS Code.
import { useQueryClient } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { Icon } from "@/components/Icon"
import { post } from "@/lib/api"
import { useGlobal } from "@/lib/queries"
import type { Addresses } from "@/lib/types"

interface Draft { dashboard_url: string; allowed_origins: string; vscode_url: string }

const toDraft = (a: Addresses): Draft => ({
  dashboard_url: a.dashboard_url, allowed_origins: a.allowed_origins.join("\n"), vscode_url: a.vscode_url,
})

/** The Dashboard addresses panel. */
export function AddressesTab() {
  const g = useGlobal()
  const qc = useQueryClient()
  const saved = g.data?.addresses
  const [draft, setDraft] = useState<Draft | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (saved) setDraft(toDraft(saved)) }, [saved])

  if (!saved || !draft) return <div className="gpanel" data-gp="addresses"><p className="small">Loading…</p></div>
  const dirty = JSON.stringify(toDraft(saved)) !== JSON.stringify(draft)
  const origins = draft.allowed_origins.split(/[\n,]/).map((o) => o.trim()).filter(Boolean)

  async function save() {
    if (!draft) return
    setBusy(true)
    try {
      const r = await post<{ api_restart: string }>("global/addresses", {
        dashboard_url: draft.dashboard_url.trim(), allowed_origins: origins, vscode_url: draft.vscode_url.trim(),
      })
      toast.success("Dashboard addresses saved.", {
        description: r.api_restart === "asked" ? "Phoenix is restarting its API to use them; this takes a few seconds." : undefined,
      })
      void qc.invalidateQueries({ queryKey: ["global"] })
      void qc.invalidateQueries({ queryKey: ["info"] })
      void qc.invalidateQueries({ queryKey: ["projects"] })
      void qc.invalidateQueries({ queryKey: ["project"] })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not save the addresses.")
    } finally {
      setBusy(false)
    }
  }

  const field = (key: keyof Draft, label: string, help: string, multi = false) => (
    <div className="field">
      <label htmlFor={`ad-${key}`}>{label}</label>
      {multi ? (
        <textarea id={`ad-${key}`} className="input mono" rows={3} value={draft[key]}
          onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
      ) : (
        <input id={`ad-${key}`} className="input mono" value={draft[key]}
          onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
      )}
      <span className="help">{help}</span>
    </div>
  )

  return (
    <div className="gpanel" data-gp="addresses">
      <section className="board" aria-labelledby="g-a">
        <div className="board-h">
          <h2 className="h2" id="g-a">Dashboard addresses</h2>
          <span className="sp small">Where Phoenix lives and which pages may change things</span>
        </div>
        <div className="board-b cfgform">
          {field("dashboard_url", "Dashboard address", "The address you open Phoenix at.")}
          {field("allowed_origins", "Allowed page addresses", "One per line. Buttons only work on pages opened from these addresses.", true)}
          {field("vscode_url", "VS Code address", "Leave empty to hide the VS Code buttons.")}
        </div>
        <div className="board-b row">
          <button type="button" className="btn btn-primary" disabled={!dirty || busy || origins.length === 0} onClick={() => void save()}>Save addresses</button>
          {dirty && <button type="button" className="btn btn-ghost" onClick={() => setDraft(toDraft(saved))}>Discard</button>}
          {origins.length === 0 && <span className="cfgerr" role="alert">Keep at least one allowed page address.</span>}
        </div>
      </section>
      <div className="blk-info tip"><Icon name="lightbulb" /><span>Changing the allowed addresses restarts Phoenix's API for a few seconds.</span></div>
    </div>
  )
}
