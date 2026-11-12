import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { Markdown } from "@/components/markdown"

const html = (t: string) => render(<Markdown text={t} />).container

describe("Markdown", () => {
  it("renders paragraphs, bold, italic and inline code", () => {
    const c = html("hello **bold** and *it* and `code`\n\nsecond")
    expect(c.querySelectorAll("p")).toHaveLength(2)
    expect(c.querySelector("strong")?.textContent).toBe("bold")
    expect(c.querySelector("em")?.textContent).toBe("it")
    expect(c.querySelector("code")?.textContent).toBe("code")
  })
  it("renders headings as h3", () => {
    const c = html("# One\n## Two")
    expect(c.querySelectorAll("h3")).toHaveLength(2)
  })
  it("renders fenced code blocks verbatim", () => {
    const c = html("```\nline **1**\n  line 2\n```")
    expect(c.querySelector("pre")?.textContent).toBe("line **1**\n  line 2")
    expect(c.querySelector("strong")).toBeNull()
  })
  it("renders bullet and numbered lists", () => {
    const c = html("- a\n- b\n\n1. x\n2. y\n3. z")
    expect(c.querySelectorAll("ul li")).toHaveLength(2)
    expect(c.querySelectorAll("ol li")).toHaveLength(3)
  })
  it("renders safe links in a new tab", () => {
    const c = html("[a](https://x.io) [b](mailto:a@b.io) [c](http://y.io)")
    const links = c.querySelectorAll("a")
    expect(links).toHaveLength(3)
    links.forEach((a) => {
      expect(a.getAttribute("target")).toBe("_blank")
      expect(a.getAttribute("rel")).toBe("noopener noreferrer")
    })
  })
  it("shows <script> as plain text", () => {
    const c = html("<script>alert(1)</script>")
    expect(c.querySelector("script")).toBeNull()
    expect(screen.getByText("<script>alert(1)</script>")).toBeTruthy()
  })
  it("shows javascript: links as plain text", () => {
    const c = html("[x](javascript:alert(1))")
    expect(c.querySelector("a")).toBeNull()
    expect(c.innerHTML).not.toMatch(/href/i)
    expect(c.textContent).toContain("[x](javascript:alert(1))")
  })
})
