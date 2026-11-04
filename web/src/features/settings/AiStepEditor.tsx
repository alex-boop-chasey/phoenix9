// The model, tools and advisor settings of one AI step, in a row that opens and closes.
import { ChevronRight } from "lucide-react"
import { useState } from "react"

import { Checkbox } from "@/components/ui/checkbox"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { getPath, listText, parseList } from "@/features/settings/dotted"
import type { LibraryTool, SettingSource } from "@/lib/types"
import { switchTool, toolState, usesDefaults } from "@/lib/tools"

const WHEN = [
  { value: "blocked", label: "Blocked" },
  { value: "before-done", label: "Before done" },
  { value: "on-demand", label: "On demand" },
]

export interface AiStepEditorProps {
  /** The step's name (the `steps.<name>` part of every key). */
  step: string
  title: string
  /** Effective values for the step (`values.steps.<name>`). */
  effective: Record<string, unknown>
  /** Flat key -> layer, from the settings data. */
  source: Record<string, SettingSource>
  /** Unsaved edits by dotted key. */
  changes: Record<string, unknown>
  /** Report one edit; `undefined` means the user cleared it. */
  onChange: (key: string, value: unknown) => void
  /** Known model names for the suggestion list. */
  models?: string[]
  /** The supported tools (from the library); when given, tools are switches instead of comma lists. */
  toolList?: LibraryTool[]
  readOnly?: boolean
}

/** One expandable row with all the AI settings of a step. */
export function AiStepEditor(props: AiStepEditorProps) {
  const { step, title, effective, source, changes, onChange, models = [], toolList, readOnly = false } = props
  const [open, setOpen] = useState(false)
  const drafts = useDrafts()
  const base = `steps.${step}`
  const id = (k: string) => `ai-${step}-${k.replace(/\./g, "-")}`
  const dirty = Object.keys(changes).some((k) => k.startsWith(`${base}.`))

  function current(key: string): unknown {
    const full = `${base}.${key}`
    if (full in changes) return changes[full]
    return source[full] === "project" ? getPath(effective, key) : undefined
  }
  const placeholder = (key: string) => {
    const v = getPath(effective, key)
    return Array.isArray(v) ? v.join(", ") : v === undefined || v === null ? "" : String(v)
  }
  const from = (key: string) => {
    const s = source[`${base}.${key}`]
    return s ? <span className="text-xs text-muted-foreground">from: {s}</span> : null
  }
  const set = (key: string, value: unknown) => onChange(`${base}.${key}`, value)

  const listField = (k: string, label: string) => {
    const full = `${base}.${k}`
    const v = current(k)
    return (
      <div className="space-y-1">
        <Label htmlFor={id(k)}>{label}</Label>
        <Input
          id={id(k)} disabled={readOnly} placeholder={placeholder(k)} autoComplete="off"
          value={full in changes ? (drafts.get(full) ?? listText(v)) : listText(v)}
          onChange={(e) => { drafts.set(full, e.target.value); set(k, parseList(e.target.value)) }}
        />
        <span className="block text-xs text-muted-foreground">Separate with commas.</span>
        {from(k)}
      </div>
    )
  }

  const numberField = (k: string, label: string) => {
    const v = current(k)
    return (
      <div className="space-y-1">
        <Label htmlFor={id(k)}>{label}</Label>
        <Input
          id={id(k)} type="number" min={1} disabled={readOnly} placeholder={placeholder(k)}
          value={v === undefined ? "" : String(v)}
          onChange={(e) => set(k, e.target.value === "" ? undefined : Number(e.target.value))}
        />
        {from(k)}
      </div>
    )
  }

  const toolSwitches = (list: LibraryTool[]) => {
    const asList = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [])
    const lists = { tools: asList(current("tools")), denied: asList(current("tools_denied")) }
    return (
      <fieldset className="space-y-1 md:col-span-2" aria-label="Tools it may use">
        <legend className="text-sm font-medium">Tools it may use</legend>
        {usesDefaults(lists) && <span className="block text-xs text-muted-foreground">Using this step's default tools. Switch one off to deny it.</span>}
        {list.map((t) => (
          <div key={t.name} className="flex items-center gap-2">
            <span className="flex min-h-11 min-w-11 items-center justify-center">
              <Switch
                id={id(`tool-${t.name}`)} aria-label={t.label} disabled={readOnly}
                checked={toolState(lists, t.name) !== "off"}
                onCheckedChange={(on) => {
                  const next = switchTool(lists, t.name, on)
                  set("tools", next.tools)
                  set("tools_denied", next.denied)
                }}
              />
            </span>
            <Label htmlFor={id(`tool-${t.name}`)} className="font-normal">{t.label}</Label>
            <span className="text-xs text-muted-foreground">{t.help}</span>
          </div>
        ))}
        {from("tools")}
      </fieldset>
    )
  }

  const advisorOn = current("advisor.on")
  const when = (current("advisor.when") ?? getPath(effective, "advisor.when") ?? []) as string[]
  const claudeMd = current("claude_md")

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="mt-2">
      <CollapsibleTrigger
        className="flex min-h-11 items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        aria-label={`${title} settings`}
      >
        <ChevronRight className={open ? "size-4 rotate-90 transition-transform" : "size-4 transition-transform"} aria-hidden />
        Model and tools
        {dirty && <span className="ml-2 text-xs">(edited)</span>}
      </CollapsibleTrigger>
      <CollapsibleContent className="w-full space-y-4 pt-2">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1">
            <Label htmlFor={id("model")}>Model</Label>
            <Input
              id={id("model")} list={id("models")} disabled={readOnly} autoComplete="off"
              placeholder={placeholder("model")} value={String(current("model") ?? "")}
              onChange={(e) => set("model", e.target.value)}
            />
            <datalist id={id("models")}>{models.map((m) => <option key={m} value={m} />)}</datalist>
            {from("model")}
          </div>
          {listField("fallback_models", "Fallback models")}
          {toolList ? toolSwitches(toolList) : <>{listField("tools", "Tools")}{listField("tools_denied", "Tools denied")}</>}
          {listField("mcp_servers", "MCP servers")}
          {listField("skills", "Skills")}
          <div className="space-y-1">
            <Label htmlFor={id("claude_md")}>CLAUDE.md</Label>
            <Select
              disabled={readOnly} value={String(claudeMd ?? getPath(effective, "claude_md") ?? "library")}
              onValueChange={(v) => set("claude_md", v)}
            >
              <SelectTrigger id={id("claude_md")} aria-label="CLAUDE.md" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {["library", "project", "both"].map((o) => <SelectItem key={o} value={o}>{o}</SelectItem>)}
              </SelectContent>
            </Select>
            {from("claude_md")}
          </div>
          {numberField("max_turns", "Max turns")}
          {numberField("timeout", "Timeout (minutes)")}
        </div>

        <fieldset className="space-y-3 rounded-md border p-3">
          <legend className="px-1 text-sm font-medium">Advisor</legend>
          <div className="flex items-center gap-2">
            <span className="flex min-h-11 min-w-11 items-center justify-center">
              <Switch
                id={id("advisor.on")} aria-label="Advisor on" disabled={readOnly}
                checked={Boolean(advisorOn ?? getPath(effective, "advisor.on"))}
                onCheckedChange={(v) => set("advisor.on", v)}
              />
            </span>
            <Label htmlFor={id("advisor.on")} className="font-normal">Use an advisor</Label>
            {from("advisor.on")}
          </div>
          <div className="space-y-1">
            <Label htmlFor={id("advisor.model")}>Advisor model</Label>
            <Input
              id={id("advisor.model")} list={id("models")} disabled={readOnly} autoComplete="off"
              placeholder={placeholder("advisor.model")} value={String(current("advisor.model") ?? "")}
              onChange={(e) => set("advisor.model", e.target.value)}
            />
            {from("advisor.model")}
          </div>
          <div className="space-y-1">
            <Label>When to ask</Label>
            <div className="flex flex-wrap gap-x-4">
              {WHEN.map((w) => (
                <div key={w.value} className="flex min-h-11 items-center gap-2">
                  <Checkbox
                    id={id(`when-${w.value}`)} aria-label={w.label} disabled={readOnly}
                    checked={when.includes(w.value)}
                    onCheckedChange={(on) =>
                      set("advisor.when", on === true
                        ? [...when.filter((x) => x !== w.value), w.value]
                        : when.filter((x) => x !== w.value))}
                  />
                  <Label htmlFor={id(`when-${w.value}`)} className="font-normal">{w.label}</Label>
                </div>
              ))}
            </div>
            {from("advisor.when")}
          </div>
          <div className="space-y-1">
            <Label htmlFor={id("advisor.instructions")}>Advisor instructions</Label>
            <Textarea
              id={id("advisor.instructions")} rows={3} disabled={readOnly}
              placeholder={placeholder("advisor.instructions")} value={String(current("advisor.instructions") ?? "")}
              onChange={(e) => set("advisor.instructions", e.target.value)}
            />
            {from("advisor.instructions")}
          </div>
        </fieldset>
      </CollapsibleContent>
    </Collapsible>
  )
}

/** Remembers the text typed into list boxes so a trailing comma is not eaten while typing. */
function useDrafts() {
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  return {
    get: (k: string) => drafts[k],
    set: (k: string, v: string) => setDrafts((d) => ({ ...d, [k]: v })),
  }
}
