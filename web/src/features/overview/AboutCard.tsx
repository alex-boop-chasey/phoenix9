// The About card: what was chosen when the project was set up, plus its size and chat.
import { Link } from "react-router"

import { Chip } from "@/components/Tag"
import { formatBytes } from "@/lib/format"
import type { Project, ProjectSetup } from "@/lib/types"

/** Words for where a project started: its template, GitHub repo, local code or nothing. */
export function startedFrom(setup: ProjectSetup | undefined): string {
  if (!setup?.source) return "Not recorded"
  if (setup.source === "template") return setup.template ? `Template ${setup.template}` : "A template"
  if (setup.source === "repo") return "A GitHub repo"
  if (setup.source === "code") return "Code on this server"
  return "Empty project"
}

const MERGING: Record<string, string> = { auto: "Merge by itself", ask: "Ask me first" }

function Pair({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (<><dt>{label}</dt><dd className={mono ? "mono" : undefined}>{value}</dd></>)
}

/** The sticky About card on the Overview. */
export function AboutCard({ project }: { project: Project }) {
  const setup = project.setup
  const none = "Not set"
  return (
    <aside className="card about stackg" aria-labelledby="ov-ab">
      <h2 className="h2" id="ov-ab" style={{ fontSize: 22 }}>About</h2>
      <p className="small">{project.description || "No description."}</p>
      <p className="eyebrow">Chosen at setup</p>
      <dl className="kv" aria-label="Chosen at setup">
        <Pair label="Kind" value={setup?.kind || project.profile || none} />
        <Pair label="Started from" value={startedFrom(setup)} />
        <Pair label="Repo owner" value={project.repo_owner || "None"} mono={!!project.repo_owner} />
        <Pair label="Default build preset" value={setup?.preset ?? none} />
        <Pair label="Merging" value={(setup?.merge && MERGING[setup.merge]) || setup?.merge || none} />
        <Pair label="Created" value={setup?.created ?? "Not recorded"} />
      </dl>
      <div className="stackg" style={{ gap: 6 }}>
        <span className="eyebrow">Services</span>
        <div className="chips">
          {project.services.length ? project.services.map((s) => <Chip key={s}>{s}</Chip>) : <span className="small">None chosen</span>}
        </div>
      </div>
      <p className="eyebrow">On this server</p>
      <dl className="kv" aria-label="On this server">
        <Pair label="Size" value={project.size == null ? "Measuring…" : formatBytes(project.size)} />
        <Pair label="Chat" value={project.chat.state === "on" ? "On" : "Off"} />
      </dl>
      <Link to={`/p/${encodeURIComponent(project.name)}/settings`} className="small">Change these in Settings</Link>
    </aside>
  )
}
