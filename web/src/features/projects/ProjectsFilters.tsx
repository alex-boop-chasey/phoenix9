// The filter bar above the projects list: search box, "Show" and "Sort" dropdowns and the count.
import { forwardRef } from "react"

import { Icon } from "@/components/Icon"

import { SORTS, STATUSES, type ProjectQuery } from "./useProjectQuery"

const STATUS_LABEL: Record<(typeof STATUSES)[number], string> = {
  all: "All projects", need: "Needs you", run: "Running", fail: "Failed", idle: "Idle",
}
const SHOW_ORDER: (typeof STATUSES)[number][] = ["all", "need", "run", "fail", "idle"]
const SORT_LABEL: Record<(typeof SORTS)[number], string> = {
  name: "Name", active: "Last active", created: "Date created", modified: "Date modified",
}

/** The search box, the Show and Sort dropdowns, and the count text. */
export const ProjectsFilters = forwardRef<HTMLInputElement, {
  query: ProjectQuery
  countText: string
  onChange: (patch: Partial<ProjectQuery>) => void
}>(function ProjectsFilters({ query, countText, onChange }, ref) {
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
      </div>
      <div className="fbar-2">
        <label className="fsel">
          <span>Show</span>
          <select className="select" id="pShow" value={query.status} onChange={(e) => onChange({ status: e.target.value as ProjectQuery["status"] })}>
            {SHOW_ORDER.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
        </label>
        <label className="fsel">
          <span>Sort</span>
          <select className="select" id="pSort" value={query.sort} onChange={(e) => onChange({ sort: e.target.value as ProjectQuery["sort"] })}>
            {SORTS.map((s) => <option key={s} value={s}>{SORT_LABEL[s]}</option>)}
          </select>
        </label>
        <span className="count" aria-live="polite">{countText}</span>
      </div>
    </div>
  )
})
