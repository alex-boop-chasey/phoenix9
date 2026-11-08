import { act, renderHook } from "@testing-library/react"
import type { ReactNode } from "react"
import { MemoryRouter, useLocation } from "react-router"

import { findRoute } from "@/lib/routes"

import { DEFAULT_QUERY, PROJECT_PARAMS, apiParams, parseQuery, useProjectQuery, withKnownOwner, writeQuery } from "./useProjectQuery"

function setup(url: string) {
  const wrapper = ({ children }: { children: ReactNode }) => <MemoryRouter initialEntries={[url]}>{children}</MemoryRouter>
  return renderHook(() => ({ ...useProjectQuery(), loc: useLocation() }), { wrapper })
}

test("reads values from the address", () => {
  const { result } = setup("/?q=bill&status=need&sort=created")
  expect(result.current.query).toEqual({ q: "bill", status: "need", owner: "all", sort: "created", attention: false })
})

test("no parameters gives the defaults; bad values fall back", () => {
  expect(setup("/").result.current.query).toEqual(DEFAULT_QUERY)
  expect(parseQuery(new URLSearchParams("status=zzz&sort=zzz&attention=yes"))).toEqual(DEFAULT_QUERY)
})

test("update writes only non-default values and keeps others", () => {
  const { result } = setup("/?other=1")
  act(() => result.current.update({ q: "hi", status: "run" }))
  expect(result.current.loc.search).toBe("?other=1&q=hi&status=run")
  act(() => result.current.update({ status: "all" }))
  expect(result.current.loc.search).toBe("?other=1&q=hi")
  expect(result.current.query.q).toBe("hi")
})

test("clear removes every filter value", () => {
  const { result } = setup("/?q=a&sort=active&attention=1&owner=x")
  act(() => result.current.clear())
  expect(result.current.loc.search).toBe("")
})

test("apiParams sends all five values", () => {
  expect(apiParams({ ...DEFAULT_QUERY, sort: "modified" })).toEqual({ q: "", status: "all", owner: "all", sort: "modified", attention: "0" })
})

test("reads owner and attention from the address", () => {
  const { result } = setup("/?owner=rebirth-wd&attention=1")
  expect(result.current.query).toMatchObject({ owner: "rebirth-wd", attention: true })
  expect(result.current.loc.search).toBe("?owner=rebirth-wd&attention=1")
})

test("an owner nobody has is ignored", () => {
  expect(withKnownOwner({ ...DEFAULT_QUERY, owner: "ghost" }, ["a"]).owner).toBe("all")
  expect(withKnownOwner({ ...DEFAULT_QUERY, owner: "a" }, ["a"]).owner).toBe("a")
})

test("every key the page writes is in the route catalogue", () => {
  const catalogue = findRoute("projects")!.params
  expect(PROJECT_PARAMS).toEqual(catalogue)
  const all = { q: "x", status: "run", owner: "o", sort: "active", attention: true } as const
  for (const key of writeQuery(new URLSearchParams(), all).keys()) expect(catalogue).toContain(key)
  expect([...writeQuery(new URLSearchParams(), all).keys()].sort()).toEqual([...catalogue].sort())
})
