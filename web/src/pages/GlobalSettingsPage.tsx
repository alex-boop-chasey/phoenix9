// Phoenix settings (/settings): title row, Health board, and the Services / Models / Updates / Dashboard addresses tabs (tab in ?tab=).
import { useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { Link, useSearchParams } from "react-router"
import { toast } from "sonner"

import { Icon, type IconName } from "@/components/Icon"
import { Wheel } from "@/components/Indicator"
import { AddressesTab } from "@/features/globalsettings/AddressesTab"
import { HealthBoard } from "@/features/globalsettings/HealthBoard"
import { ModelsTab } from "@/features/globalsettings/ModelsTab"
import { ServicesTab } from "@/features/globalsettings/ServicesTab"
import { UpdatesTab } from "@/features/globalsettings/UpdatesTab"
import { api } from "@/lib/api"
import { useDoctor, useInfo } from "@/lib/queries"

const TABS: { key: string; label: string; icon: IconName }[] = [
  { key: "services", label: "Services", icon: "plugs-connected" },
  { key: "models", label: "Models", icon: "cpu" },
  { key: "updates", label: "Updates", icon: "arrow-circle-up" },
  { key: "addresses", label: "Dashboard addresses", icon: "globe" },
]

/** The Settings page for all of Phoenix. */
export default function GlobalSettingsPage() {
  const [params, setParams] = useSearchParams()
  const tab = TABS.some((t) => t.key === params.get("tab")) ? (params.get("tab") as string) : "services"
  const qc = useQueryClient()
  const doctor = useDoctor()
  const info = useInfo()
  const [checking, setChecking] = useState(false)
  const upd = info.data?.update
  const newest = upd?.supported && upd.available ? upd.newest : ""

  async function runCheck() {
    setChecking(true)
    try {
      const r = await api.doctor("full")
      qc.setQueryData(["doctor"], r)
      const bad = r.checks.filter((c) => !c.ok).length
      if (bad === 0) toast.success("Health check done", { description: `All ${r.checks.length} checks passed.` })
      else toast.error("Health check found problems", { description: `${bad} of ${r.checks.length} checks failed.` })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "The health check did not run.")
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="stackg" style={{ gap: 20 }}>
      <div className="title-row">
        <div><h1 className="h1" id="t-global">Phoenix settings</h1><p className="lead">Settings for all of Phoenix.</p></div>
        <div className="title-acts">
          <Link className="btn btn-ghost" to="/styles"><Icon name="palette" />Style reference</Link>
          <button type="button" className="btn btn-primary" disabled={checking} onClick={() => void runCheck()}>
            {checking ? <><Wheel />Checking…</> : <><Icon name="stethoscope" />Run health check</>}
          </button>
        </div>
      </div>
      <HealthBoard result={doctor.data} loading={doctor.isLoading} error={doctor.isError ? doctor.error.message : undefined} />
      <nav className="tabs" aria-label="Phoenix settings tabs">
        {TABS.map((t) => (
          <button
            key={t.key} type="button" className="tab" data-g={t.key}
            aria-current={tab === t.key ? "page" : "false"}
            onClick={() => setParams(t.key === "services" ? {} : { tab: t.key }, { replace: true })}
          >
            <Icon name={t.icon} />{t.label}
            {t.key === "updates" && newest && <span className="tc new">{newest}</span>}
          </button>
        ))}
      </nav>
      {tab === "services" && <ServicesTab />}
      {tab === "models" && <ModelsTab />}
      {tab === "updates" && <UpdatesTab />}
      {tab === "addresses" && <AddressesTab />}
    </div>
  )
}
