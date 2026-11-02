// One hook that keeps the project search and filter in the page address, so a link reproduces the view.
import { useCallback, useMemo } from "react"
import { useSearchParams } from "react-router"

export const STATUSES = ["all", "run", "fail", "idle", "need"] as const
export const SORTS = ["name", "active", "size"] as const

export interface ProjectQuery {
  q: string
  status: (typeof STATUSES)[number]
  owner: string
  sort: (typeof SORTS)[number]
  attention: boolean
}

export const DEFAULT_QUERY: ProjectQuery = { q: "", status: "all", owner: "all", sort: "name", attention: false }

/** Read the query from address parameters; unknown values fall back to the defaults. */
export function parseQuery(params: URLSearchParams): ProjectQuery {
  const status = params.get("status") as ProjectQuery["status"]
  const sort = params.get("sort") as ProjectQuery["sort"]
  return {
    q: params.get("q") ?? "",
    status: STATUSES.includes(status) ? status : "all",
    owner: params.get("owner") || "all",
    sort: SORTS.includes(sort) ? sort : "name",
    attention: params.get("attention") === "1",
  }
}

/** Write a query as address parameters, leaving out everything that is still the default. */
export function writeQuery(base: URLSearchParams, query: ProjectQuery): URLSearchParams {
  const next = new URLSearchParams(base)
  for (const key of Object.keys(DEFAULT_QUERY)) next.delete(key)
  if (query.q) next.set("q", query.q)
  if (query.status !== "all") next.set("status", query.status)
  if (query.owner !== "all") next.set("owner", query.owner)
  if (query.sort !== "name") next.set("sort", query.sort)
  if (query.attention) next.set("attention", "1")
  return next
}

/** The query as parameters for the projects API (always sends all five, so the new reply shape comes back). */
export function apiParams(query: ProjectQuery): Record<string, string> {
  return { q: query.q, status: query.status, owner: query.owner, sort: query.sort, attention: query.attention ? "1" : "0" }
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
