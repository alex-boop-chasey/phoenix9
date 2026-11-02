// The New project order sheet: seven numbered steps made of open tiles.
import { useEffect, useState, type ReactNode } from "react"
import { Link } from "react-router"

import { Icon, type IconName } from "@/components/Icon"
import { RepoPicker, useNameCheck } from "@/features/projects/ProjectForm"
import {
  PROFILES, newRepoApplies, rememberOwner, rememberedOwner, type FormValues, type SourceKind,
} from "@/features/projects/formModel"
import { KeysForm } from "@/features/keys/KeysForm"
import { useGithubRepos, useInfo, useLibraryProfiles, useLibraryServices, useLibraryTemplates, useServices } from "@/lib/queries"
import type { KeyInput } from "@/lib/types"


const SOURCES: { value: SourceKind; label: string; hint: string; icon: IconName }[] = [
  { value: "empty", label: "Empty", hint: "Start with a blank folder.", icon: "file-text" },
  { value: "repo", label: "Existing GitHub repo", hint: "Copy a repo you already have.", icon: "github-logo" },
  { value: "template", label: "Template", hint: "A ready-made starter.", icon: "cube" },
  { value: "code", label: "On this server", hint: "Code already in a folder here.", icon: "folder-open" },
]

const PROFILE_LOOK: Record<string, { title: string; hint: string; icon: IconName }> = {
  web: { title: "Web app", hint: "Sites and apps", icon: "globe" },
  mobile: { title: "Mobile app", hint: "Expo and native", icon: "device-mobile" },
  desktop: { title: "Desktop app", hint: "Tauri", icon: "desktop" },
  "python-script": { title: "Python script", hint: "Command line tools", icon: "file-py" },
  research: { title: "Research", hint: "Notes and reports", icon: "book-open" },
  platform: { title: "Platform", hint: "Services and tooling", icon: "stack" },
}

const SERVICE_ICON: Record<string, IconName> = {
  github: "github-logo", supabase: "hard-drives", sentry: "warning-octagon",
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

/** Step 1 and 2: the name (with the live check) and the description. */
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
      <Step n={2} id="np-step-desc">
        <div className="field">
          <label htmlFor="pf-desc">Description</label>
          <textarea className="textarea" id="pf-desc" rows={3} value={value.description} onChange={(e) => set({ description: e.target.value })} />
          <span className="help">A few lines. They go into the project's CLAUDE.md.</span>
        </div>
      </Step>
    </>
  )
}

/** Step 3: where the code comes from, with its follow-up. */
function SourceStep({ value, set }: Props) {
  const github = useGithubRepos()
  const templates = useLibraryTemplates()
  const connected = !!github.data?.connected
  const templateNames = templates.data?.map((t) => t.name) ?? []
  const [custom, setCustom] = useState(false)
  const showCustom = custom || (!!value.template && !templateNames.includes(value.template))

  function pickTemplate(name: string) {
    const known = templates.data?.find((t) => t.name === name)
    setCustom(false)
    set({ template: name, ...(known ? { profile: known.profile } : {}) })
  }

  return (
    <Step n={3} id="np-step-source">
      <span className="lbl" id="srcL">Where does the code come from?</span>
      <div className="tiles" role="radiogroup" aria-labelledby="srcL">
        {SOURCES.map((s) => (
          <Tile
            key={s.value} type="radio" name="src" title={s.label} hint={s.hint} icon={s.icon}
            checked={value.source === s.value}
            onChange={() => set({ source: s.value, newRepo: newRepoApplies(s.value) })}
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
          <span className="lbl" id="tplL">Template</span>
          <div className="tiles" role="radiogroup" aria-labelledby="tplL">
            {templates.data?.map((t) => (
              <Tile
                key={t.name} type="radio" name="tpl" title={t.title} hint={PROFILE_LOOK[t.profile]?.title ?? t.profile}
                checked={!showCustom && value.template === t.name} onChange={() => pickTemplate(t.name)}
              />
            ))}
            <Tile
              type="radio" name="tpl" title="Another GitHub template…" hint="Type owner/name" dashed
              checked={showCustom} onChange={() => { setCustom(true); set({ template: "" }) }}
            />
          </div>
          {showCustom && (
            <input
              className="input mono" aria-label="GitHub template" placeholder="owner/name" value={value.template}
              onChange={(e) => set({ template: e.target.value })}
            />
          )}
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

/** Step 4: what kind of project (the profiles from the library). */
function ProfileStep({ value, set }: Props) {
  const profiles = useLibraryProfiles()
  const names = profiles.data?.profiles.map((p) => p.name) ?? [...PROFILES]
  return (
    <Step n={4} id="np-step-profile">
      <span className="lbl" id="profL">What kind of project?</span>
      <div className="tiles" role="radiogroup" aria-labelledby="profL">
        {names.map((n) => {
          const look = PROFILE_LOOK[n]
          const title = look?.title ?? profiles.data?.profiles.find((p) => p.name === n)?.title ?? n
          return (
            <Tile
              key={n} type="radio" name="prof" title={title} hint={look?.hint} icon={look?.icon ?? "stack"}
              checked={value.profile === n} onChange={() => set({ profile: n })}
            />
          )
        })}
      </div>
    </Step>
  )
}

/** Step 5: the new GitHub repo switch and the owner tiles. */
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
    <Step n={5} id="np-step-repo">
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

/** Step 6: services as multi-select tiles with a connection dot. */
function ServicesStep({ value, set }: Props) {
  const library = useLibraryServices()
  const status = useServices()
  const github = useGithubRepos()
  const connectedOf = (name: string): boolean =>
    name === "github" ? !!github.data?.connected : !!status.data?.services.find((s) => s.name === name)?.connected
  const toggle = (name: string, on: boolean) =>
    set({ services: on ? [...value.services, name] : value.services.filter((x) => x !== name) })
  const n = value.services.length
  return (
    <Step n={6} id="np-step-services">
      <span className="lbl" id="svcL">Services</span>
      <div className="tiles" role="group" aria-labelledby="svcL">
        {library.data?.services.map((s) => {
          const on = connectedOf(s.name)
          return (
            <Tile
              key={s.name} type="checkbox" name={`sv-${s.name}`} title={s.title} multi icon={SERVICE_ICON[s.name] ?? "plugs-connected"}
              checked={value.services.includes(s.name)} onChange={(c) => toggle(s.name, c)}
            >
              <span className={`cdot${on ? "" : " no"}`}><i />{on ? "Connected" : "Not connected"}</span>
            </Tile>
          )
        })}
      </div>
      <p className="small">{n === 0 ? "None selected" : `${n} selected`}</p>
    </Step>
  )
}

interface Props {
  value: FormValues
  set: (patch: Partial<FormValues>) => void
  onNameOk: (ok: boolean) => void
}

/** The seven steps of the order sheet, in order. */
export function OrderSheet({
  value, onChange, onNameOk, onRows,
}: {
  value: FormValues
  onChange: (v: FormValues) => void
  onNameOk: (ok: boolean) => void
  onRows: (rows: KeyInput[], pending: boolean) => void
}) {
  const props: Props = { value, set: (patch) => onChange({ ...value, ...patch }), onNameOk }
  return (
    <ol className="osteps">
      <NameSteps {...props} />
      <SourceStep {...props} />
      <ProfileStep {...props} />
      <RepoStep {...props} />
      <ServicesStep {...props} />
      <Step n={7} id="np-step-keys">
        <span className="lbl">Project keys</span>
        <KeysForm mode="local" draft onRowsChange={onRows} />
      </Step>
    </ol>
  )
}

