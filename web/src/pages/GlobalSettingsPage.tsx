// Global settings (#/settings): GitHub, services, default models, Telegram and Phoenix updates.
import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"
import type { ReactNode } from "react"

import { ConfirmDialog } from "@/components/ConfirmDialog"
import { ErrorState } from "@/components/ErrorState"
import { PageHeader } from "@/components/PageHeader"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { GithubConnectForm } from "@/features/keys/GithubConnectForm"
import { ServiceConnectForm } from "@/features/keys/ServiceConnectForm"
import { UpdatePanel } from "@/features/updates/UpdatePanel"
import { post } from "@/lib/api"
import { keys, useGlobal, useKeysAudit, useServices } from "@/lib/queries"
import type { ServiceStatus } from "@/lib/types"

const AI_STEPS = ["planner", "builder", "check-writer", "reviewer"]

const Status = ({ on }: { on: boolean }) =>
  on ? <Badge>Connected</Badge> : <Badge variant="secondary">Not connected</Badge>

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">{children}</CardContent>
    </Card>
  )
}

function ServiceRow({ service, onChanged }: { service: ServiceStatus; onChanged: () => void }) {
  const [open, setOpen] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const keysOnly = service.support === "keys-only"
  const users = service.used_by ?? []
  const endpoints = service.endpoints ?? {}

  async function disconnect() {
    try {
      await post(endpoints.disconnect ?? "", { yes: true })
      toast.success(`${service.title || service.name} disconnected.`)
      onChanged()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not disconnect.")
    }
  }

  return (
    <li className="flex flex-col gap-2 rounded-md border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{service.title || service.name}</span>
        {keysOnly ? <Badge variant="secondary">No account connection needed</Badge> : <Status on={service.connected} />}
        {!keysOnly && !service.connected && endpoints.connect && (
          <Button size="sm" variant="outline" className="ml-auto" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? "Hide" : "Connect"}
          </Button>
        )}
        {!keysOnly && service.connected && endpoints.disconnect && (
          <Button size="sm" variant="outline" className="ml-auto" onClick={() => setConfirm(true)}>Disconnect</Button>
        )}
      </div>
      {service.description && <p className="text-muted-foreground">{service.description}</p>}
      {!keysOnly && service.connected && service.checked && (
        <p className="text-muted-foreground">Last check: {service.checked}</p>
      )}
      {users.length > 0 && <p className="text-muted-foreground">Used by: {users.join(", ")}</p>}
      {open && endpoints.connect && (
        <ServiceConnectForm endpoint={endpoints.connect} keyNames={service.account_keys ?? []} onDone={onChanged} />
      )}
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title={`Disconnect ${service.title || service.name}?`}
        body={users.length > 0
          ? `This removes the saved account keys. These projects use it: ${users.join(", ")}.`
          : "This removes the saved account keys. No project uses it."}
        confirmLabel="Disconnect"
        destructive
        onConfirm={() => void disconnect()}
      />
    </li>
  )
}

function AuditDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const audit = useKeysAudit(open)
  const problems = audit.data?.problems ?? []
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Keys audit</DialogTitle>
          <DialogDescription>Problems with saved keys. Values are never shown.</DialogDescription>
        </DialogHeader>
        {audit.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {audit.error && <p className="text-sm text-destructive">{audit.error.message}</p>}
        {audit.data && problems.length === 0 && <p className="text-sm">No problems found.</p>}
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {problems.map((p, i) => <li key={i} className="break-words">{p}</li>)}
        </ul>
      </DialogContent>
    </Dialog>
  )
}

/** The Settings page for all of Phoenix. */
export default function GlobalSettingsPage() {
  const global = useGlobal()
  const services = useServices()
  const qc = useQueryClient()
  const [auditOpen, setAuditOpen] = useState(false)
  const g = global.data
  const github = g?.github
  const connectEndpoint = g?.supported.github_connect ? g.endpoints?.github_connect : undefined

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Settings" description="Settings for all of Phoenix." />
      {global.isError && <ErrorState error={global.error} onRetry={() => void global.refetch()} />}

      <Section title="GitHub">
        {github?.connected ? (
          <>
            <div><Badge>Connected</Badge></div>
            <ul className="list-disc pl-5">
              {github.accounts.map((a) => <li key={a}>{a}</li>)}
            </ul>
          </>
        ) : (
          github && (
            <>
              <div><Badge variant="secondary">Not connected</Badge></div>
              <p className="text-muted-foreground">
                Connecting GitHub from this page comes in a later update; for now ask the Phoenix chat to connect it.
              </p>
            </>
          )
        )}
        {connectEndpoint && <GithubConnectForm endpoint={connectEndpoint} />}
      </Section>

      <Section title="Services">
        {services.data?.supported && (
          <ul className="flex flex-col gap-2">
            {services.data.services.map((s) => (
              <ServiceRow
                key={s.name}
                service={s}
                onChanged={() => {
                  void qc.invalidateQueries({ queryKey: keys.services() })
                  void qc.invalidateQueries({ queryKey: ["keys-audit"] })
                }}
              />
            ))}
          </ul>
        )}
        {services.data && !services.data.supported && (
          <p className="text-muted-foreground">Connecting services is not available yet.</p>
        )}
        <div>
          <Button size="sm" variant="link" className="px-0" onClick={() => setAuditOpen(true)}>Keys audit</Button>
        </div>
        <AuditDialog open={auditOpen} onOpenChange={setAuditOpen} />
      </Section>

      <Section title="Default models">
        {g && (
          <ul className="flex flex-col gap-1">
            {AI_STEPS.map((s) => {
              const m = g.default_models[s]
              if (!m) return null
              return (
                <li key={s}>
                  <span className="font-medium">{s}</span>: {m.model}
                  {m.fallback_models.length > 0 && (
                    <span className="text-muted-foreground"> (then {m.fallback_models.join(", ")})</span>
                  )}
                </li>
              )
            })}
          </ul>
        )}
        <p className="text-muted-foreground">Change these per project in a project's Settings tab.</p>
      </Section>

      <Section title="Telegram">
        {g && <div><Status on={g.telegram.connected} /></div>}
      </Section>

      <UpdatePanel />
    </div>
  )
}
