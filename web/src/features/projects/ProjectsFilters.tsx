// The filter bar above the projects list: search, "Needs my attention", status segments, owner, sort and count.
import { forwardRef } from "react"

import { Icon } from "@/components/Icon"
import type { ProjectQueryResult } from "@/lib/types"

import { SORTS, STATUSES, type ProjectQuery } from "./useProjectQuery"

const STATUS_LABEL: Record<string, string> = { all: "All", run: "Running", fail: "Failed", idle: "Idle" }
const SORT_LABEL: Record<(typeof SORTS)[number], string> = { name: "Name", active: "Recently active", size: "Size" }

/** The search box, attention toggle, status segments, owner and sort selects, and the count text. */
export const ProjectsFilters = forwardRef<HTMLInputElement, {
  query: ProjectQuery
  counts: ProjectQueryResult["counts"]
  owners: string[]
  countText: string
  onChange: (patch: Partial<ProjectQuery>) => void
}>(function ProjectsFilters({ query, counts, owners, countText, onChange }, ref) {
  return (
    <div className="fbar" role="search" aria-label="Search and filter projects">
      <div className="fbar-1">
        <div className="with-ico">
          <Icon name="magnifying-glass" />
          <label className="sr" htmlFor="pSearch">Search projects</label>
          <input
            ref={ref} className="input" id="pSearch" type="search" placeholder="Search projects"
            value={query.q} onChange={(e) => onChange({ q: e.target.value })}
          />
          <span className="kbd">/</span>
        </div>
        <button
          type="button" className="attn-tog" aria-pressed={query.attention}
          onClick={() => onChange({ attention: !query.attention })}
        >
          <Icon name="bell-ringing" className="bell" />Needs my attention<span className="n">{counts.need}</span>
          <span className="knob" aria-hidden="true" />
        </button>
      </div>
      <div className="fbar-2">
        <div className="segs" role="group" aria-label="Status">
          {STATUSES.filter((s) => s !== "need").map((s) => (
            <button key={s} type="button" aria-pressed={query.status === s} onClick={() => onChange({ status: s })}>
              {STATUS_LABEL[s]} <span>{counts[s as keyof typeof counts]}</span>
            </button>
          ))}
        </div>
        <label className="sr" htmlFor="pOwner">Owner</label>
        <select className="select" id="pOwner" value={query.owner} onChange={(e) => onChange({ owner: e.target.value })}>
          <option value="all">All owners</option>
          {owners.map((o) => <option key={o} value={o}>{o}</option>)}
          <option value="none">No repo</option>
        </select>
        <label className="sr" htmlFor="pSort">Sort</label>
        <select className="select" id="pSort" value={query.sort} onChange={(e) => onChange({ sort: e.target.value as ProjectQuery["sort"] })}>
          {SORTS.map((s) => <option key={s} value={s}>Sort: {SORT_LABEL[s]}</option>)}
        </select>
        <span className="count" aria-live="polite">{countText}</span>
      </div>
    </div>
  )
})
