// The project fields, shared by New project (create) and the Project settings (edit).
import { useEffect, useState } from "react"
import { Check, ChevronsUpDown } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { api } from "@/lib/api"
import { useGithubRepos, useInfo, useLibraryServices, useLibraryTemplates } from "@/lib/queries"
import type { NameCheck } from "@/lib/types"
import {
  NAME_RE, PROFILES, newRepoApplies, rememberOwner, rememberedOwner, type FormValues, type SourceKind,
} from "@/features/projects/formModel"
import { Link } from "react-router"

const SOURCES: { value: SourceKind; label: string }[] = [
  { value: "empty", label: "Empty" },
  { value: "repo", label: "Existing GitHub repo" },
  { value: "template", label: "Template" },
  { value: "code", label: "Code already on this server" },
]

const CUSTOM = "__custom__"

function useNameCheck(name: string, enabled: boolean): { message: string; ok: boolean } {
  const [result, setResult] = useState<{ name: string; check: NameCheck } | null>(null)
  const localBad = !!name && !NAME_RE.test(name)
  useEffect(() => {
    if (!enabled || !name || localBad) return
    const timer = setTimeout(() => {
      api.checkName(name).then((check) => setResult({ name, check })).catch(() => setResult(null))
    }, 300)
    return () => clearTimeout(timer)
  }, [name, enabled, localBad])
  if (localBad) {
    return { ok: false, message: "Use lowercase letters, digits and dashes, starting with a letter or digit (41 characters at most)." }
  }
  if (result && result.name === name) return result.check
  return { ok: false, message: "" }
}

/** Tells the page whether the name is accepted; shown by the form under the name field. */
export function ProjectForm({
  mode, value, onChange, onNameOk, sourceText,
}: {
  mode: "create" | "edit"
  value: FormValues
  onChange: (v: FormValues) => void
  onNameOk?: (ok: boolean) => void
  sourceText?: string
}) {
  const creating = mode === "create"
  const info = useInfo()
  const github = useGithubRepos(creating)
  const templates = useLibraryTemplates()
  const services = useLibraryServices()
  const check = useNameCheck(value.name, creating)
  const connected = !!github.data?.connected
  const accounts = info.data?.github.accounts ?? []
  const set = (patch: Partial<FormValues>) => onChange({ ...value, ...patch })

  useEffect(() => onNameOk?.(check.ok && !!value.name), [check.ok, value.name, onNameOk])

  // Pick a default owner once the accounts are known.
  useEffect(() => {
    if (!creating || value.owner || !accounts.length) return
    const saved = rememberedOwner()
    const wanted = saved && accounts.includes(saved) ? saved : accounts.includes("rebirth-wd") ? "rebirth-wd" : accounts[0]!
    onChange({ ...value, owner: wanted })
  })

  function pickTemplate(name: string) {
    const known = templates.data?.find((t) => t.name === name)
    set({ template: name === CUSTOM ? "" : name, ...(known ? { profile: known.profile } : {}) })
  }

  const templateNames = templates.data?.map((t) => t.name) ?? []
  const customTemplate = !!value.template && !templateNames.includes(value.template)
  const [custom, setCustom] = useState(false)
  const showCustom = custom || customTemplate

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <Label htmlFor="pf-name">Name</Label>
        <Input
          id="pf-name" value={value.name} readOnly={!creating} autoComplete="off"
          aria-invalid={creating && !!value.name && !check.ok && !!check.message}
          aria-describedby="pf-name-msg" onChange={(e) => set({ name: e.target.value })}
        />
        {creating && (
          <p id="pf-name-msg" className={check.ok ? "text-sm text-green-600 dark:text-green-400" : "text-sm text-destructive"}>
            {check.message}
          </p>
        )}
      </div>

      <div className="space-y-2">
        <Label htmlFor="pf-desc">Description</Label>
        <Textarea
          id="pf-desc" rows={3} value={value.description} onChange={(e) => set({ description: e.target.value })}
        />
        <p className="text-xs text-muted-foreground">A few lines. They go into the project's CLAUDE.md.</p>
      </div>

      <div className="space-y-2">
        <Label id="pf-source-label">Source</Label>
        {creating ? (
          <RadioGroup
            aria-labelledby="pf-source-label" value={value.source}
            onValueChange={(v) => {
              const source = v as SourceKind
              set({ source, newRepo: newRepoApplies(source) })
            }}
          >
            {SOURCES.map((s) => (
              <div key={s.value} className="flex items-center gap-2">
                <RadioGroupItem value={s.value} id={`pf-src-${s.value}`} />
                <Label htmlFor={`pf-src-${s.value}`} className="font-normal">{s.label}</Label>
              </div>
            ))}
          </RadioGroup>
        ) : (
          <div className="space-y-1">
            <Input
              aria-label="GitHub repo" placeholder="owner/name" value={value.repo} autoComplete="off"
              onChange={(e) => set({ repo: e.target.value })}
            />
            {sourceText && <p className="text-xs text-muted-foreground">{sourceText}</p>}
          </div>
        )}
      </div>

      {creating && value.source === "repo" && connected && (
        <RepoPicker repos={github.data?.repos ?? []} value={value.repo} onPick={(repo) => set({ repo })} />
      )}
      {creating && value.source === "repo" && !connected && (
        <p className="text-sm text-muted-foreground">
          Connect GitHub in <Link className="underline" to="/settings">Settings</Link> to pick a repo.
        </p>
      )}

      {creating && value.source === "template" && (
        <div className="space-y-2">
          <Label htmlFor="pf-template">Template</Label>
          <Select
            value={showCustom ? CUSTOM : value.template}
            onValueChange={(v) => { setCustom(v === CUSTOM); pickTemplate(v) }}
          >
            <SelectTrigger id="pf-template" aria-label="Template" className="w-full"><SelectValue placeholder="Choose a template" /></SelectTrigger>
            <SelectContent>
              {templates.data?.map((t) => <SelectItem key={t.name} value={t.name}>{t.title}</SelectItem>)}
              <SelectItem value={CUSTOM}>Another GitHub template…</SelectItem>
            </SelectContent>
          </Select>
          {showCustom && (
            <Input
              aria-label="GitHub template" placeholder="owner/name" value={value.template}
              onChange={(e) => set({ template: e.target.value })}
            />
          )}
        </div>
      )}

      {creating && value.source === "code" && (
        <div className="space-y-2">
          <Label htmlFor="pf-path">Folder on this server</Label>
          <Input id="pf-path" placeholder="/srv/..." value={value.path} onChange={(e) => set({ path: e.target.value })} />
        </div>
      )}

      <div className="space-y-2">
        <Label htmlFor="pf-profile">Profile</Label>
        <Select value={value.profile} onValueChange={(profile) => set({ profile })}>
          <SelectTrigger id="pf-profile" aria-label="Profile" className="w-full"><SelectValue /></SelectTrigger>
          <SelectContent>
            {PROFILES.map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      {creating && newRepoApplies(value.source) && (
        connected ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Switch
                id="pf-newrepo" checked={value.newRepo} aria-label="New GitHub repo"
                onCheckedChange={(newRepo) => set({ newRepo })}
              />
              <Label htmlFor="pf-newrepo">Create a new GitHub repo</Label>
            </div>
            {value.newRepo && (
              <Select
                value={value.owner}
                onValueChange={(owner) => { rememberOwner(owner); set({ owner }) }}
              >
                <SelectTrigger aria-label="Owner" className="w-full"><SelectValue placeholder="Owner" /></SelectTrigger>
                <SelectContent>
                  {accounts.map((a) => <SelectItem key={a} value={a}>{a}</SelectItem>)}
                </SelectContent>
              </Select>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Connect GitHub in <Link className="underline" to="/settings">Settings</Link> to create a repo.
          </p>
        )
      )}

      <div className="space-y-2">
        <Label>Services</Label>
        {services.data?.services.map((s) => (
          <div key={s.name} className="flex items-center gap-2">
            <Checkbox
              id={`pf-svc-${s.name}`} aria-label={s.title}
              checked={value.services.includes(s.name)}
              onCheckedChange={(on) =>
                set({ services: on === true ? [...value.services, s.name] : value.services.filter((x) => x !== s.name) })}
            />
            <Label htmlFor={`pf-svc-${s.name}`} className="font-normal">{s.title}</Label>
          </div>
        ))}
        <p className="text-xs text-muted-foreground">Connecting service accounts comes in a later update.</p>
      </div>
    </div>
  )
}

function RepoPicker({
  repos, value, onPick,
}: {
  repos: { full_name: string; owner: string; private: boolean }[]
  value: string
  onPick: (repo: string) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="space-y-2">
      <Label htmlFor="pf-repo">GitHub repo</Label>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button id="pf-repo" type="button" variant="outline" role="combobox" aria-expanded={open} className="w-full justify-between">
            {value || "Choose a repo"}
            <ChevronsUpDown className="opacity-50" aria-hidden />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
          <Command>
            <CommandInput placeholder="Search repos" />
            <CommandList>
              <CommandEmpty>No repo found.</CommandEmpty>
              {repos.map((r) => (
                <CommandItem key={r.full_name} value={r.full_name} onSelect={() => { onPick(r.full_name); setOpen(false) }}>
                  <Check className={value === r.full_name ? "opacity-100" : "opacity-0"} aria-hidden />
                  {r.full_name}
                  {r.private && <span className="ml-auto text-xs text-muted-foreground">private</span>}
                </CommandItem>
              ))}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  )
}
