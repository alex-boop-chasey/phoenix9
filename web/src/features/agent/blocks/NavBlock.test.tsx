import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import { NavBlock } from "@/features/agent/blocks/NavBlock"

afterEach(() => { window.location.hash = "" })

const resolved = {
  links: [{ hash: "#/settings?section=models", label: "Model settings" }, { hash: "#/new", label: "New project" }],
  dropped: [{ link: 3, to: "nowhere", reason: "no such page" }],
}

describe("NavBlock", () => {
  it("shows one button per resolved link", () => {
    render(<NavBlock json="{}" resolved={resolved} />)
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Model settings", "New project"])
  })
  it("click moves the dashboard", () => {
    render(<NavBlock json="{}" resolved={resolved} />)
    fireEvent.click(screen.getByRole("button", { name: "New project" }))
    expect(window.location.hash).toBe("#/new")
  })
  it("shows nothing without links", () => {
    const { container } = render(<NavBlock json="{}" resolved={{ links: [], dropped: [] }} />)
    expect(container.textContent).toBe("")
  })
})
