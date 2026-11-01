// Global settings (#/settings): GitHub, services, default models, Telegram and Phoenix updates.
import { useState } from "react"
import type { ReactNode } from "react"

import { ErrorState } from "@/components/ErrorState"
import { PageHeader } from "@/components/PageHeader"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { GithubConnectForm } from "@/features/keys/GithubConnectForm"
import { KeysForm } from "@/features/keys/KeysForm"
import { UpdatePanel } from "@/features/updates/UpdatePanel"
import { useGlobal, useServices } from "@/lib/queries"
import type { ServiceStatus } from "@/lib/types"

const PLANNED = ["GitHub", "Supabase", "Resend", "Sentry", "Stripe", "Clerk", "Sanity", "Mux", "OpenRouter"]
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

function ServiceRow({ service }: { service: ServiceStatus }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="flex flex-col gap-2 rounded-md border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{service.title || service.name}</span>
        <Status on={service.connected} />
        <Button size="sm" variant="outline" className="ml-auto" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Hide keys" : "Keys"}
        </Button>
      </div>
      {open && <KeysForm mode="saved" project={service.name} />}
    </li>
  )
}

/** The Settings page for all of Phoenix. */
export default function GlobalSettingsPage() {
  const global = useGlobal()
  const services = useServices()
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
        {services.data?.supported ? (
          <ul className="flex flex-col gap-2">
            {services.data.services.map((s) => <ServiceRow key={s.name} service={s} />)}
          </ul>
        ) : (
          services.data && (
            <>
              <p className="text-muted-foreground">Connecting services comes in a later update.</p>
              <ul className="flex flex-col gap-2 text-muted-foreground">
                {PLANNED.map((n) => (
                  <li key={n} className="flex items-center gap-2">
                    <span>{n}</span>
                    <Badge variant="secondary">Not connected</Badge>
                  </li>
                ))}
              </ul>
            </>
          )
        )}
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
