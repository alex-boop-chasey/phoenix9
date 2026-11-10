// Maps a tool's component name to our React components; all text is drawn as plain text from typed data.
import type { ReactNode } from "react"

import { KeyInputCard, keyAskFrom } from "./keycard"

/** Card data for one project, as the Phoenix pack sends it. */
export interface ProjectCardData { name: string; status: string; last_used: string; link?: string }

/** One tool call as the panel tracks it: running until its result arrives. */
export interface ToolCallItem { toolCallId: string; toolName: string; running: boolean; component?: string; data?: unknown }

function isText(v: unknown): v is string { return typeof v === "string" }

/** Pick out the projects that fit the card shape; null when the data does not fit. */
export function projectsFrom(data: unknown): ProjectCardData[] | null {
  const list = (data as { projects?: unknown } | null | undefined)?.projects
  if (!Array.isArray(list)) return null
  const out: ProjectCardData[] = []
  for (const p of list) {
    if (!p || typeof p !== "object") return null
    const { name, status, last_used, link } = p as Record<string, unknown>
    if (!isText(name)) return null
    out.push({ name, status: isText(status) ? status : "", last_used: isText(last_used) ? last_used : "", link: isText(link) ? link : undefined })
  }
  return out
}

function openHash(link: string) {
  window.location.hash = link.startsWith("#") ? link : `#${link}`
}

/** One project: name, status, last used; a click opens it. */
export function MiniProjectCard({ project, onOpen }: { project: ProjectCardData; onOpen?: (p: ProjectCardData) => void }) {
  const open = () => (onOpen ? onOpen(project) : openHash(project.link || `#/p/${project.name}`))
  return (
    <button type="button" className="card w-full text-left" data-testid="mini-project-card" onClick={open}>
      <strong>{project.name}</strong>
      <span className="block text-sm">{project.status || "unknown"}</span>
      <span className="block text-xs text-muted-foreground">Last used: {project.last_used || "not yet"}</span>
    </button>
  )
}

/** A list of project cards. */
export function ProjectCards({ projects, onOpen }: { projects: ProjectCardData[]; onOpen?: (p: ProjectCardData) => void }) {
  return (
    <section className="flex flex-col gap-2" aria-label="Projects" data-testid="project-cards">
      {projects.map((p) => <MiniProjectCard key={p.name} project={p} onOpen={onOpen} />)}
    </section>
  )
}

/** What shows when a card's data does not fit its shape. */
function Fallback({ tool }: { tool: string }) {
  return <p data-testid="card-fallback">Used {tool}, but the result could not be shown.</p>
}

/** The cards we can draw, chosen by component name. */
export const COMPONENTS: Record<string, (props: { data: unknown; tool: string; callId?: string; onOpen?: (p: ProjectCardData) => void }) => ReactNode> = {
  project_cards: ({ data, tool, onOpen }) => {
    const projects = projectsFrom(data)
    return projects ? <ProjectCards projects={projects} onOpen={onOpen} /> : <Fallback tool={tool} />
  },
  KeyInputCard: ({ data, tool, callId }) => {
    const ask = keyAskFrom(data)
    return ask && callId ? <KeyInputCard ask={ask} callId={callId} /> : <Fallback tool={tool} />
  },
}

/** One tool call: running state, then its card, or a plain "Used <tool>" line. */
export function ToolCall({ call, onOpen }: { call: ToolCallItem; onOpen?: (p: ProjectCardData) => void }) {
  if (call.running) return <p data-testid="tool-running" aria-busy="true">Running {call.toolName}…</p>
  const Draw = call.component ? COMPONENTS[call.component] : undefined
  if (!Draw) return <p data-testid="tool-used">Used {call.toolName}</p>
  return <>{Draw({ data: call.data, tool: call.toolName, callId: call.toolCallId, onOpen })}</>
}
