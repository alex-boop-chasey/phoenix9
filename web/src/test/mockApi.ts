// Stubs fetch for tests: a table of "METHOD /api/path" -> data (or a function of the request).
import { vi } from "vitest"
import { agentMessages, agentSessions, agentStatuses } from "@/test/fixtures"

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
    if (data instanceof Failure) {
      return new Response(JSON.stringify({ ok: false, message: data.message, ...data.extra }),
        { status: data.status, headers: { "Content-Type": "application/json" } })
    }
    return new Response(JSON.stringify({ ok: true, data }), { status: 200, headers: { "Content-Type": "application/json" } })
  })
  vi.stubGlobal("fetch", fn)
  return { calls, fetch: fn }
}

/** Routes for every /api/agent* endpoint (spread into a mockApi table; override single routes after). */
export function agentRoutes(): Record<string, Route> {
  return {
    "GET /api/agent": agentStatuses.idle,
    "GET /api/agent/messages": agentMessages,
    "GET /api/agent/sessions": agentSessions,
    "GET /api/agent/stream": { ok: true },
    "POST /api/agent/send": { sent: true, at: "2026-11-07T10:02:00Z", after_line: 8 },
  }
}
