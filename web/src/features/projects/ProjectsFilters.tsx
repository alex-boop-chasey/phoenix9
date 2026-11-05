// The filter bar above the projects list: search box, "Show" and "Sort" dropdowns and the count.
import { forwardRef, useEffect, useRef, useState } from "react"

import { Icon } from "@/components/Icon"

import { SORTS, STATUSES, type ProjectQuery } from "./useProjectQuery"

const STATUS_LABEL: Record<(typeof STATUSES)[number], string> = {
  all: "All projects", need: "Needs you", run: "Running", fail: "Failed", idle: "Idle",
}
const SHOW_ORDER: (typeof STATUSES)[number][] = ["all", "need", "run", "fail", "idle"]
const SORT_LABEL: Record<(typeof SORTS)[number], string> = {
  name: "Name", active: "Last active", created: "Date created", modified: "Date modified",
}

/** How long typing can pause before the search text goes to the address (and the server). */
export const SEARCH_DEBOUNCE_MS = 250

/** The typed search text: shown at once, sent on (via onCommit) after a pause or on Enter; follows outside changes. */
function useDebouncedSearch(value: string, onCommit: (q: string) => void) {
  const [text, setText] = useState(value)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const commit = useRef(onCommit)
  useEffect(() => {
    commit.current = onCommit
  })
  const cancel = () => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = undefined
  }
  useEffect(() => {
    // The address changed (a link, Clear filters, or our own commit): show that text and drop any pending commit.
    cancel()
    setText(value)
  }, [value])
  useEffect(() => cancel, [])
  const type = (next: string) => {
    setText(next)
    cancel()
    timer.current = setTimeout(() => { timer.current = undefined; commit.current(next) }, SEARCH_DEBOUNCE_MS)
  }
  const flush = () => {
    if (!timer.current) return
    cancel()
    commit.current(text)
  }
  return { text, type, flush }
}

/** The search box, the Show and Sort dropdowns, and the count text. */
export const ProjectsFilters = forwardRef<HTMLInputElement, {
  query: ProjectQuery
  countText: string
  onChange: (patch: Partial<ProjectQuery>) => void
}>(function ProjectsFilters({ query, countText, onChange }, ref) {
  const search = useDebouncedSearch(query.q, (q) => onChange({ q }))
  return (
    <div className="fbar" role="search" aria-label="Search and filter projects">
      <div className="fbar-1">
        <div className="with-ico">
          <Icon name="magnifying-glass" />
          <label className="sr" htmlFor="pSearch">Search projects</label>
          <input
            ref={ref} className="input" id="pSearch" type="search" placeholder="Search projects"
            value={search.text} onChange={(e) => search.type(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") search.flush() }}
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
