// One hook that keeps the project search and filter in the page address, so a link reproduces the view.
import { useCallback, useMemo } from "react"
import { useSearchParams } from "react-router"

import { findRoute } from "@/lib/routes"

/** The parameter names the address may carry for the projects page, taken from the route catalogue. */
export const PROJECT_PARAMS = findRoute("projects")!.params
const [Q, STATUS, OWNER, SORT, ATTENTION] = ["q", "status", "owner", "sort", "attention"].map((k) => {
  if (!PROJECT_PARAMS.includes(k)) throw new Error(`route catalogue lacks projects param ${k}`)
  return k
}) as [string, string, string, string, string]

export const STATUSES = ["all", "run", "fail", "idle", "need"] as const
export const SORTS = ["name", "active", "created", "modified"] as const

export interface ProjectQuery {
  q: string
  status: (typeof STATUSES)[number]
  owner: string
  sort: (typeof SORTS)[number]
  attention: boolean
}

export const ALL_OWNER = "all"
export const DEFAULT_QUERY: ProjectQuery = { q: "", status: "all", owner: ALL_OWNER, sort: "name", attention: false }

/** Read the query from address parameters; unknown values fall back to the defaults. */
export function parseQuery(params: URLSearchParams): ProjectQuery {
  const status = params.get(STATUS) as ProjectQuery["status"]
  const sort = params.get(SORT) as ProjectQuery["sort"]
  return {
    q: params.get(Q) ?? "",
    status: STATUSES.includes(status) ? status : "all",
    owner: params.get(OWNER) || ALL_OWNER,
    sort: SORTS.includes(sort) ? sort : "name",
    attention: params.get(ATTENTION) === "1",
  }
}

/** Write a query as address parameters, leaving out everything that is still the default. */
export function writeQuery(base: URLSearchParams, query: ProjectQuery): URLSearchParams {
  const next = new URLSearchParams(base)
  for (const key of PROJECT_PARAMS) next.delete(key)
  if (query.q) next.set(Q, query.q)
  if (query.status !== "all") next.set(STATUS, query.status)
  if (query.owner !== ALL_OWNER) next.set(OWNER, query.owner)
  if (query.sort !== "name") next.set(SORT, query.sort)
  if (query.attention) next.set(ATTENTION, "1")
  return next
}

/** The query with an owner that no project has turned back into "all" (unknown values are ignored). */
export function withKnownOwner(query: ProjectQuery, owners: string[]): ProjectQuery {
  return owners.includes(query.owner) ? query : { ...query, owner: ALL_OWNER }
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
