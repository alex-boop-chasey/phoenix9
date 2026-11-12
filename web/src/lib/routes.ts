// The dashboard pages the agent may point at; same list as phoenix9/routes.py (a test keeps them equal).

export type RouteEntry = { name: string; params: string[] }

export const ROUTES: RouteEntry[] = [
  { name: "projects", params: ["q", "status", "owner", "sort", "attention"] },
  { name: "new", params: [] },
  { name: "p/<name>/overview", params: ["gate"] },
  { name: "p/<name>/build", params: ["run", "wizard"] },
  { name: "p/<name>/logs", params: ["run", "step", "task", "kind", "log"] },
  { name: "p/<name>/settings", params: ["section", "key"] },
  { name: "settings", params: ["section"] },
  { name: "doc", params: ["path"] },
]

/** The catalogue entry for a route such as "p/test-site/build", or undefined. */
export function findRoute(to: string): RouteEntry | undefined {
  const m = /^p\/([^/]+)\/([a-z]+)$/.exec(to)
  const generic = m ? `p/<name>/${m[2]}` : to
  return ROUTES.find((r) => r.name === generic)
}

/** The URL hash for a route and its params (catalogue order, URL-encoded, empty ones left out); null if unknown. */
export function routeHash(to: string, params: Record<string, unknown> = {}): string | null {
  const entry = findRoute(to)
  if (!entry) return null
  const query = entry.params
    .filter((k) => params[k] !== undefined && params[k] !== null && params[k] !== "")
    .map((k) => `${k}=${encodeURIComponent(String(params[k]))}`)
    .join("&")
  const path = to === "projects" ? "/" : `/${to}`
  return `#${path}${query ? `?${query}` : ""}`
}
