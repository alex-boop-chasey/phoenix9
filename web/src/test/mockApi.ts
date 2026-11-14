// Stubs fetch for tests: a table of "METHOD /api/path" -> data (or a function of the request; a Response is sent as it is).
import { vi } from "vitest"

export interface MockRequest {
  method: string
  path: string
  query: Record<string, string>
  headers: Record<string, string>
  body: unknown
}

export type Route = unknown | ((req: MockRequest) => unknown)

/** A route answer that is a failure: the server's `{ok: false, message, ...extra}` with this HTTP status. */
export class Failure {
  constructor(public status: number, public message: string, public extra: Record<string, unknown> = {}) {}
}
export const failure = (status: number, message: string, extra: Record<string, unknown> = {}) =>
  new Failure(status, message, extra)
export interface Call extends MockRequest {}

/** A route answer sent as it is, with no `{ok, data}` wrapper (the agent service's own answers). */
export class Raw {
  constructor(public body: unknown, public status = 200) {}
}
export const raw = (body: unknown, status = 200) => new Raw(body, status)

/** Replace fetch with the routes table; unknown routes throw loudly. Returns the recorded calls. */
export function mockApi(routes: Record<string, Route>) {
  const calls: Call[] = []
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, location.href)
    const method = (init?.method ?? "GET").toUpperCase()
    const path = url.pathname.replace(/^.*?(\/api\/)/, "/api/")
    const headers = Object.fromEntries(Object.entries((init?.headers ?? {}) as Record<string, string>))
    const raw = typeof init?.body === "string" ? init.body : undefined
    const req: MockRequest = {
      method, path, headers, query: Object.fromEntries(url.searchParams), body: raw ? JSON.parse(raw) : undefined,
    }
    calls.push(req)
    const route = routes[`${method} ${path}`]
    if (route === undefined && !(`${method} ${path}` in routes)) {
      throw new Error(`mockApi: no route for ${method} ${path}`)
    }
    const data = typeof route === "function" ? (route as (r: MockRequest) => unknown)(req) : route
    if (data instanceof Response) return data
    if (data instanceof Raw) {
      return new Response(JSON.stringify(data.body), { status: data.status, headers: { "Content-Type": "application/json" } })
    }
    if (data instanceof Failure) {
      return new Response(JSON.stringify({ ok: false, message: data.message, ...data.extra }),
        { status: data.status, headers: { "Content-Type": "application/json" } })
    }
    return new Response(JSON.stringify({ ok: true, data }), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fn)
  return { calls, fetch: fn }
}

/** Routes for the new agent service under /api/agent-next/ (no conversation yet; spread, then override). */
export function agentNextRoutes(): Record<string, Route> {
  return {
    "GET /api/agent-next/status": raw({ running: true, key_present: true, pack: "phoenix", model: "m" }),
    "GET /api/agent-next/threads": raw({ threads: [] }),
    "GET /api/agent-next/spend": raw({ month: "2026-11", used_share: 0.1, state: "plenty" }),
    "POST /api/agent-next/threads": raw({ id: "t9" }, 201),
  }
}
