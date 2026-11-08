import { act, render } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { scrollToAndHighlight, useScrollToId } from "./focus"

function Probe({ id, ready = true }: { id: string; ready?: boolean }) {
  useScrollToId(id, ready)
  return <div id="a">a</div>
}

describe("scrollToAndHighlight", () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it("scrolls smoothly, glows for 2 s, then stops", () => {
    const el = document.createElement("div")
    el.scrollIntoView = vi.fn()
    scrollToAndHighlight(el)
    expect(el.scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center" })
    expect(el.classList.contains("focus-glow")).toBe(true)
    act(() => { vi.advanceTimersByTime(2000) })
    expect(el.classList.contains("focus-glow")).toBe(false)
  })

  it("does not animate the scroll under reduced motion", () => {
    vi.stubGlobal("matchMedia", () => ({ matches: true }))
    const el = document.createElement("div")
    el.scrollIntoView = vi.fn()
    scrollToAndHighlight(el)
    expect(el.scrollIntoView).toHaveBeenCalledWith({ behavior: "auto", block: "center" })
    vi.unstubAllGlobals()
  })

  it("ignores a missing element and an unknown id", () => {
    expect(() => scrollToAndHighlight(null)()).not.toThrow()
    render(<Probe id="nope" />)
  })

  it("the hook glows the element with that id once ready", () => {
    const { container, rerender } = render(<Probe id="a" ready={false} />)
    expect(container.querySelector(".focus-glow")).toBeNull()
    rerender(<Probe id="a" />)
    expect(container.querySelector("#a.focus-glow")).not.toBeNull()
  })
})
