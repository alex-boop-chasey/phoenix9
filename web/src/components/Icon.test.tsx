import { render } from "@testing-library/react"

import { Icon } from "@/components/Icon"
import { ICONS } from "@/components/iconSprite"

test("renders a known icon with its artwork", () => {
  const { container } = render(<Icon name="flame" />)
  const svg = container.querySelector("svg")!
  expect(svg).toHaveAttribute("data-icon", "flame")
  expect(svg.querySelectorAll("path")).toHaveLength(2)
})

test("is hidden from screen readers unless it has a title", () => {
  const { container, rerender } = render(<Icon name="check" />)
  expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true")
  rerender(<Icon name="check" title="Passed" />)
  expect(container.querySelector("svg")).toHaveAttribute("aria-label", "Passed")
})

test("bundles the mockup icon set", () => {
  expect(Object.keys(ICONS).length).toBeGreaterThanOrEqual(80)
})
