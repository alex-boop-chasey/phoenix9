// Phoenix settings > Services: one row per service (Claude, GitHub, Supabase... Telegram) with Configure and Connect / Disconnect.
import { useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { toast } from "sonner"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { ErrorState } from "@/components/ErrorState"
import { Icon } from "@/components/Icon"
import { RelativeTime } from "@/components/RelativeTime"
import { post } from "@/lib/api"
import { useGlobalServices } from "@/lib/queries"
import type { ServiceStatus } from "@/lib/types"
import { ConfigureDialog } from "./ConfigureDialog"
import { serviceIcon } from "./serviceIcon"

function statusLine(s: ServiceStatus): React.ReactNode {
  if (s.support === "keys-only") return "Add its keys in each project's Settings."
  const used = s.used_by?.length ? ` · Used by ${s.used_by.join(", ")}` : ""
  if (!s.connected) return "Not checked"
  if (s.checked === "ok") return <>Key checked OK{s.checked_at ? <>, <RelativeTime iso={s.checked_at} /></> : null}{used}</>
  if (s.checked?.startsWith("failed")) return `Key refused: ${s.checked.replace("failed: ", "")}${used}`
  return `Saved, not checked${used}`
}

function Row({ s, onConfigure, onDisconnect }: { s: ServiceStatus; onConfigure: () => void; onDisconnect: () => void }) {
  const keysOnly = s.support === "keys-only"
  const name = s.title || s.name
  return (
    <div className="lrow" data-service={s.name}>
      <div className="who">
        <span className="ico"><Icon name={serviceIcon(s.name)} /></span>
        <div style={{ minWidth: 0 }}><b>{name}</b><span>{s.description}</span></div>
      </div>
      <div className="st">
        {keysOnly
          ? <span className="badge b-info"><Icon name="plugs" />No account needed</span>
          : s.connected
            ? <span className="badge b-ok"><Icon name="check-circle" />Connected</span>
            : <span className="badge b-info"><Icon name="plugs" />Not connected</span>}
        <span>{statusLine(s)}</span>
      </div>
      <div className="lacts">
        {!keysOnly && s.endpoints?.connect && (
          <>
            <button type="button" className={`btn btn-sm ${s.connected ? "btn-secondary" : "btn-primary"}`}
              aria-label={`${s.connected ? "Configure" : "Connect"} ${name}`} onClick={onConfigure}>
              {s.connected ? <><Icon name="sliders-horizontal" />Configure</> : "Connect"}
            </button>
            {s.website && (
              <a className="btn btn-ghost btn-sm" href={s.website} target="_blank" rel="noopener noreferrer"
                aria-label={`${name} website`}>Website</a>
            )}
            {s.connected && <button type="button" className="btn btn-ghost btn-sm" aria-label={`Disconnect ${name}`} onClick={onDisconnect}>Disconnect</button>}
          </>
        )}
      </div>
    </div>
  )
}

/** The Services panel. */
export function ServicesTab() {
  const q = useGlobalServices()
  const qc = useQueryClient()
  const [cfg, setCfg] = useState<string | null>(null)
  const [disc, setDisc] = useState<ServiceStatus | null>(null)
  const rows = q.data?.services ?? []
  const counted = rows.filter((r) => r.support !== "keys-only")
  const on = counted.filter((r) => r.connected).length

  async function disconnect(s: ServiceStatus) {
    try {
      await post(s.endpoints?.disconnect ?? "", { yes: true })
      toast.success(`${s.title || s.name} disconnected.`)
      void qc.invalidateQueries({ queryKey: ["global-services"] })
      void qc.invalidateQueries({ queryKey: ["services"] })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not disconnect.")
    }
  }

  return (
    <div className="gpanel" data-gp="services">
      <section className="board" aria-labelledby="g-s">
        <div className="board-h">
          <h2 className="h2" id="g-s">Services</h2>
          {q.data && <span className="sp"><span className="light ok" id="svcCount"><i></i>{on} of {counted.length} connected</span></span>}
        </div>
        {q.isError && <ErrorState error={q.error} onRetry={() => void q.refetch()} />}
        {q.isLoading && <p className="small" style={{ padding: 20 }}>Loading…</p>}
        <div id="svcRows" className="llist">
          {rows.map((s) => <Row key={s.name} s={s} onConfigure={() => setCfg(s.name)} onDisconnect={() => setDisc(s)} />)}
        </div>
      </section>
      <div className="blk-info">
        <Icon name="info" />
        <span>Keys here are Phoenix's own and shared by every project. Values for one project only (like its Supabase project address) go in that project's Settings, under Project keys.</span>
      </div>
      <ConfigureDialog service={rows.find((r) => r.name === cfg) ?? null} onClose={() => setCfg(null)} />
      <ConfirmDialog
        open={disc !== null}
        onOpenChange={(o) => { if (!o) setDisc(null) }}
        title={`Disconnect ${disc?.title ?? ""}?`}
        body={disc?.used_by?.length
          ? `Its saved keys are removed. These projects use it: ${disc.used_by.join(", ")}.`
          : `Its saved keys are removed. Projects that use ${disc?.title ?? "it"} can't set it up until you connect it again.`}
        confirmLabel="Disconnect"
        destructive
        onConfirm={() => { const s = disc; setDisc(null); if (s) void disconnect(s) }}
      />
    </div>
  )
}
