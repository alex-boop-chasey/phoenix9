// The New project order sheet: three wizard slides made of open tiles (name and source, type and services, keys).
import { useEffect, useMemo, type ReactNode } from "react"
import { Link } from "react-router"

import { Icon, type IconName } from "@/components/Icon"
import { RepoPicker } from "@/features/projects/RepoPicker"
import { useNameCheck } from "@/features/projects/useNameCheck"
import {
  PROFILES, frameworkApplies, newRepoApplies, rememberOwner, rememberedOwner, type FormValues, type SourceKind,
} from "@/features/projects/formModel"
import { KeysForm, type RowsSummary, type WantedKey } from "@/features/keys/KeysForm"
import { useGithubRepos, useInfo, useLibraryProfiles, useLibraryServices, useLibraryTemplates, useServices } from "@/lib/queries"
import type { KeyInput, ServiceKey } from "@/lib/types"


const SOURCES: { value: SourceKind; label: string; hint: string; icon: IconName }[] = [
  { value: "empty", label: "Empty", hint: "Start with a blank folder.", icon: "file-text" },
  { value: "repo", label: "Existing GitHub repo", hint: "Copy a repo you already have.", icon: "github-logo" },
  { value: "template", label: "GitHub template", hint: "A template repo on GitHub.", icon: "cube" },
  { value: "code", label: "On this server", hint: "Code already in a folder here.", icon: "folder-open" },
]

export const PROFILE_LOOK: Record<string, { title: string; hint: string; icon: IconName }> = {
  web: { title: "Web app", hint: "Sites and apps", icon: "globe" },
  mobile: { title: "Mobile app", hint: "Expo and native", icon: "device-mobile" },
  desktop: { title: "Desktop app", hint: "Tauri", icon: "desktop" },
  "python-script": { title: "Python script", hint: "Command line tools", icon: "file-py" },
  research: { title: "Research", hint: "Notes and reports", icon: "book-open" },
  platform: { title: "Platform", hint: "Services and tooling", icon: "stack" },
}

export const SERVICE_ICON: Record<string, IconName> = {
  github: "github-logo", supabase: "hard-drives", sentry: "warning-octagon", cloudflare: "cloud",
}

/** One open tile: a hidden radio or checkbox inside a label; the name is the input's accessible name. */
function Tile({
  type, name, checked, onChange, title, hint, icon, multi, dashed, mono, children,
}: {
  type: "radio" | "checkbox"
  name: string
  checked: boolean
  onChange: (on: boolean) => void
  title: string
  hint?: string
  icon?: IconName
  multi?: boolean
  dashed?: boolean
  mono?: boolean
  children?: ReactNode
}) {
  return (
    <label className={`tile${multi ? " multi" : ""}${dashed ? " dashed" : ""}`}>
      <input type={type} name={name} checked={checked} aria-label={title} onChange={(e) => onChange(e.target.checked)} />
      <span className="mark-r" />
      {icon && <Icon name={icon} size="lg" className="ti" />}
      <b className={mono ? "mono" : undefined}>{title}</b>
      {hint && <small>{hint}</small>}
      {children}
    </label>
  )
}

function Step({ n, id, children }: { n: number; id: string; children: ReactNode }) {
  return (
    <li className="ostep" id={id}>
      <span className="sn">{n}</span>
      <div className="body">{children}</div>
    </li>
  )
}

/** Step 1: the name (with the live check). */
function NameSteps({ value, set, onNameOk }: Props) {
  const check = useNameCheck(value.name, true)
  useEffect(() => onNameOk(check.ok && !!value.name), [check.ok, value.name, onNameOk])
  const bad = !!value.name && !check.ok && !!check.message
  return (
    <>
      <Step n={1} id="np-step-name">
        <div className="field">
          <label htmlFor="pf-name">Name</label>
          <input
            className="input mono" id="pf-name" value={value.name} autoComplete="off" aria-invalid={bad}
            aria-describedby="pf-name-msg" onChange={(e) => set({ name: e.target.value })}
          />
          <span
            id="pf-name-msg" className={check.ok ? "valid" : "reason"} aria-live="polite"
            style={check.ok || !check.message ? undefined : { alignItems: "flex-start" }}
          >
            {check.ok && <Icon name="check-circle" />}
            {check.message}
          </span>
        </div>
      </Step>
    </>
  )
}

/** Step 2: where the code comes from, with its follow-up. */
function SourceStep({ value, set }: Props) {
  const github = useGithubRepos()
  const connected = !!github.data?.connected

  return (
    <Step n={2} id="np-step-source">
      <span className="lbl" id="srcL">Where does the code come from?</span>
      <div className="tiles" role="radiogroup" aria-labelledby="srcL">
        {SOURCES.map((s) => (
          <Tile
            key={s.value} type="radio" name="src" title={s.label} hint={s.hint} icon={s.icon}
            checked={value.source === s.value}
            onChange={() => set({ source: s.value, newRepo: newRepoApplies(s.value), framework: frameworkApplies(s.value) ? value.framework : "" })}
          />
        ))}
      </div>
      {value.source === "repo" && (
        <div className="follow">
          {connected
            ? <RepoPicker repos={github.data?.repos ?? []} value={value.repo} onPick={(repo) => set({ repo })} />
            : <p className="small">Connect GitHub in <Link to="/settings">Settings</Link> to pick a repo.</p>}
        </div>
      )}
      {value.source === "template" && (
        <div className="follow">
          <div className="field">
            <label htmlFor="pf-template">GitHub template</label>
            <input
              className="input mono" id="pf-template" placeholder="owner/name" value={value.template}
              onChange={(e) => set({ template: e.target.value })}
            />
          </div>
        </div>
      )}
      {value.source === "code" && (
        <div className="follow">
          <div className="field">
            <label htmlFor="pf-path">Folder on this server</label>
            <input className="input mono" id="pf-path" placeholder="/srv/..." value={value.path} onChange={(e) => set({ path: e.target.value })} />
          </div>
        </div>
      )}
    </Step>
  )
}

/** Step 3: the new GitHub repo switch and the owner tiles. */
function RepoStep({ value, set }: Props) {
  const info = useInfo()
  const github = useGithubRepos()
  const accounts = info.data?.github.accounts ?? []
  const connected = !!github.data?.connected

  // Pick a default owner once the accounts are known.
  useEffect(() => {
    if (value.owner || !accounts.length) return
    const saved = rememberedOwner()
    set({ owner: saved && accounts.includes(saved) ? saved : accounts.includes("rebirth-wd") ? "rebirth-wd" : accounts[0]! })
  })

  return (
    <Step n={3} id="np-step-repo">
      {!newRepoApplies(value.source) ? (
        <p className="small">An existing repo or folder keeps its own repo, so no new one is made.</p>
      ) : !connected ? (
        <p className="small">Connect GitHub in <Link to="/settings">Settings</Link> to create a repo.</p>
      ) : (
        <>
          <label className="sw-line" htmlFor="pf-newrepo">
            <input
              type="checkbox" role="switch" className="switch" id="pf-newrepo" aria-label="New GitHub repo"
              checked={value.newRepo} onChange={(e) => set({ newRepo: e.target.checked })}
            />
            <span className="lbl">Create a new GitHub repo</span>
          </label>
          {value.newRepo && (
            <>
              <span className="lbl" id="ownL">Owner</span>
              <div className="tiles" role="radiogroup" aria-labelledby="ownL">
                {accounts.map((a) => (
                  <Tile
                    key={a} type="radio" name="own" title={a} mono icon={accounts.indexOf(a) === 0 ? "buildings" : "user"}
                    checked={value.owner === a} onChange={() => { rememberOwner(a); set({ owner: a }) }}
                  />
                ))}
              </div>
            </>
          )}
        </>
      )}
    </Step>
  )
}

/** The keys the ticked services ask for (each name once). */
export function wantedKeys(
  services: { name: string; project_keys: ServiceKey[] }[] | undefined, ticked: string[],
): WantedKey[] {
  const out: WantedKey[] = []
  for (const s of services ?? []) {
    if (!ticked.includes(s.name)) continue
    for (const k of s.project_keys) if (!out.some((o) => o.name === k.name)) out.push({ service: s.name, ...k })
  }
  return out
}

/** The Type and Framework pickers shown above the service tiles. */
function TypeFramework({ value, set }: Pick<Props, "value" | "set">) {
  const profiles = useLibraryProfiles()
  const templates = useLibraryTemplates()
  const types = profiles.data?.profiles.length ? profiles.data.profiles.map((p) => p.name) : PROFILES
  const starters = (templates.data ?? []).filter((t) => t.profile === value.profile)
  const applies = frameworkApplies(value.source)
  const pickType = (profile: string) =>
    set({ profile, framework: starters.length && profile === value.profile ? value.framework : "" })
  return (
    <>
      <span className="lbl" id="typeL">Type</span>
      <div className="tiles" role="radiogroup" aria-labelledby="typeL">
        {types.map((name) => (
          <Tile
            key={name} type="radio" name="type" title={PROFILE_LOOK[name]?.title ?? name} hint={PROFILE_LOOK[name]?.hint}
            icon={PROFILE_LOOK[name]?.icon} checked={value.profile === name} onChange={() => pickType(name)}
          />
        ))}
      </div>
      {value.profile && (
        <>
          <span className="lbl" id="fwL">Framework</span>
          {applies ? (
            <div className="tiles" role="radiogroup" aria-labelledby="fwL">
              <Tile
                type="radio" name="fw" title="None" hint="Start empty" checked={!value.framework}
                onChange={() => set({ framework: "" })}
              />
              {starters.map((t) => (
                <Tile
                  key={t.name} type="radio" name="fw" title={t.title} checked={value.framework === t.name}
                  onChange={() => set({ framework: t.name })}
                />
              ))}
            </div>
          ) : (
            <>
              <div className="tiles" role="radiogroup" aria-labelledby="fwL" aria-disabled="true">
                <fieldset disabled style={{ display: "contents" }}>
                  <Tile type="radio" name="fw" title="None" hint="Start empty" checked onChange={() => {}} />
                </fieldset>
              </div>
              <p className="small">The code you're bringing already has its framework.</p>
            </>
          )}
        </>
      )}
    </>
  )
}

/** Slide 2: type, framework, then services as multi-select tiles; a service that needs Phoenix-wide keys says so. */
function ServicesStep({ value, set }: Props) {
  const library = useLibraryServices()
  const status = useServices()
  const github = useGithubRepos()
  // Only a service that needs Phoenix-wide account keys can be "not set up yet"; keys-only ones are always fine.
  const needsSetup = (name: string): boolean => {
    if (name === "github") return github.data ? !github.data.connected : false
    const row = status.data?.services.find((s) => s.name === name)
    return !!row && !row.connected && (row.account_keys?.length ?? 0) > 0
  }
  const toggle = (name: string, on: boolean) =>
    set({ services: on ? [...value.services, name] : value.services.filter((x) => x !== name) })
  const n = value.services.length
  const rows = wantedKeys(library.data?.services, value.services).length
  return (
    <div className="np-slide-b" id="np-step-services">
      <TypeFramework value={value} set={set} />
      <span className="lbl" id="svcL">Services</span>
      <div className="tiles" role="group" aria-labelledby="svcL">
        {library.data?.services.map((s) => {
          const setup = needsSetup(s.name)
          return (
            <Tile
              key={s.name} type="checkbox" name={`sv-${s.name}`} title={s.title} multi icon={SERVICE_ICON[s.name] ?? "plugs-connected"}
              checked={value.services.includes(s.name)} onChange={(c) => toggle(s.name, c)}
            >
              {setup && (
                <small className="reason">
                  <Link to="/settings" onClick={(e) => e.stopPropagation()}>Set up in Phoenix settings first</Link>
                </small>
              )}
            </Tile>
          )
        })}
      </div>
      <p className="small">{n === 0 ? "None selected" : `${n} selected · adds ${rows} key ${rows === 1 ? "row" : "rows"} on the Keys step`}</p>
    </div>
  )
}

interface Props {
  value: FormValues
  set: (patch: Partial<FormValues>) => void
  onNameOk: (ok: boolean) => void
}

/** The three slides of the order sheet; all stay mounted (so typed keys survive) and only `slide` is shown. */
export function OrderSheet({
  value, slide, onChange, onNameOk, onRows,
}: {
  value: FormValues
  slide: number
  onChange: (v: FormValues) => void
  onNameOk: (ok: boolean) => void
  onRows: (rows: KeyInput[], pending: boolean, summary: RowsSummary) => void
}) {
  const library = useLibraryServices()
  const wanted = useMemo(() => wantedKeys(library.data?.services, value.services), [library.data, value.services])
  const props: Props = { value, set: (patch) => onChange({ ...value, ...patch }), onNameOk }
  return (
    <>
      <div hidden={slide !== 1} data-slide-body={1}>
        <ol className="osteps">
          <NameSteps {...props} />
          <SourceStep {...props} />
          <RepoStep {...props} />
        </ol>
      </div>
      <div hidden={slide !== 2} data-slide-body={2}>
        <ServicesStep {...props} />
      </div>
      <div hidden={slide !== 3} data-slide-body={3}>
        <div className="np-slide-b" id="np-step-keys">
          <span className="lbl">Project keys</span>
          <KeysForm mode="local" draft envUpload onRowsChange={onRows} wanted={wanted} />
        </div>
      </div>
    </>
  )
}
