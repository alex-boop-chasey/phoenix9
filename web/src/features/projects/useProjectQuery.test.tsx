import { act, renderHook } from "@testing-library/react"
import type { ReactNode } from "react"
import { MemoryRouter, useLocation } from "react-router"

import { DEFAULT_QUERY, apiParams, parseQuery, useProjectQuery } from "./useProjectQuery"

function setup(url: string) {
  const wrapper = ({ children }: { children: ReactNode }) => <MemoryRouter initialEntries={[url]}>{children}</MemoryRouter>
  return renderHook(() => ({ ...useProjectQuery(), loc: useLocation() }), { wrapper })
}

test("reads values from the address", () => {
  const { result } = setup("/?q=bill&status=need&sort=created")
  expect(result.current.query).toEqual({ q: "bill", status: "need", sort: "created" })
})

test("no parameters gives the defaults; bad values fall back", () => {
  expect(setup("/").result.current.query).toEqual(DEFAULT_QUERY)
  expect(parseQuery(new URLSearchParams("status=zzz&sort=zzz&attention=1&owner=x"))).toEqual(DEFAULT_QUERY)
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
