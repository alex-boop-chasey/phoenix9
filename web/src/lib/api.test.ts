import { ApiError, api, apiBase, eventsUrl } from "@/lib/api"
import { mockApi } from "@/test/mockApi"

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.replaceState(null, "", "/")
})

test("base url keeps path prefix", () => {
  window.history.replaceState(null, "", "/proxy/8091/#/p/x")
  expect(apiBase().pathname).toBe("/proxy/8091/api/")
  expect(eventsUrl("x")).toContain("/proxy/8091/api/events?project=x")
})

test("post sends X-Phoenix header and JSON", async () => {
  const { calls } = mockApi({ "POST /api/gates/g.1/answer": { ok: 1 } })
  await api.answerGate("g.1", "approve", "go")
  expect(calls[0]!.method).toBe("POST")
  expect(calls[0]!.headers["X-Phoenix"]).toBe("1")
  expect(calls[0]!.headers["Content-Type"]).toBe("application/json")
  expect(calls[0]!.body).toEqual({ action: "approve", note: "go" })
})

test("ok false throws ApiError with server message", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ ok: false, message: "No such project." }), { status: 404 })),
  )
  const err = await api.project("nope").catch((e) => e)
  expect(err).toBeInstanceOf(ApiError)
  expect(err.status).toBe(404)
  expect(err.message).toBe("No such project.")
})

test("network failure message is plain", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))))
  const err = await api.info().catch((e) => e)
  expect(err).toBeInstanceOf(ApiError)
  expect(err.message).toBe("Phoenix is not answering.")
})
