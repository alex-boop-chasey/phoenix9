// One hook that keeps the project search and filter in the page address, so a link reproduces the view.
import { useCallback, useMemo } from "react"
import { useSearchParams } from "react-router"

export const STATUSES = ["all", "run", "fail", "idle", "need"] as const
export const SORTS = ["name", "active", "created", "modified"] as const

export interface ProjectQuery {
  q: string
  status: (typeof STATUSES)[number]
  sort: (typeof SORTS)[number]
}

export const DEFAULT_QUERY: ProjectQuery = { q: "", status: "all", sort: "name" }

/** Read the query from address parameters; unknown values fall back to the defaults. */
export function parseQuery(params: URLSearchParams): ProjectQuery {
  const status = params.get("status") as ProjectQuery["status"]
  const sort = params.get("sort") as ProjectQuery["sort"]
  return {
    q: params.get("q") ?? "",
    status: STATUSES.includes(status) ? status : "all",
    sort: SORTS.includes(sort) ? sort : "name",
  }
}

/** Write a query as address parameters, leaving out everything that is still the default. */
export function writeQuery(base: URLSearchParams, query: ProjectQuery): URLSearchParams {
  const next = new URLSearchParams(base)
  for (const key of [...Object.keys(DEFAULT_QUERY), "owner", "attention"]) next.delete(key)
  if (query.q) next.set("q", query.q)
  if (query.status !== "all") next.set("status", query.status)
  if (query.sort !== "name") next.set("sort", query.sort)
  return next
}

/** The query as parameters for the projects API (always sends all five, so the new reply shape comes back; owner and attention are no longer chosen on the page). */
export function apiParams(query: ProjectQuery): Record<string, string> {
  return { q: query.q, status: query.status, owner: "all", sort: query.sort, attention: "0" }
}

/** The search and filter values from the page address, plus a setter that changes some of them. */
export function useProjectQuery() {
  const [params, setParams] = useSearchParams()
  const query = useMemo(() => parseQuery(params), [params])
  const update = useCallback(
    (patch: Partial<ProjectQuery>) => setParams((p) => writeQuery(p, { ...parseQuery(p), ...patch }), { replace: true }),
    [setParams],
  )
  const clear = useCallback(() => update(DEFAULT_QUERY), [update])
  return { query, update, clear }
}
