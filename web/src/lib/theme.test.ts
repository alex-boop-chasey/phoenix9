import { applyTheme, getTheme, readTheme, resetThemeCache, toggleTheme } from "@/lib/theme"

beforeEach(() => {
  localStorage.clear()
  resetThemeCache()
  document.documentElement.className = ""
  vi.restoreAllMocks()
})

test("dark by default", () => {
  expect(readTheme()).toBe("dark")
  expect(getTheme()).toBe("dark")
  applyTheme(getTheme())
  expect(document.documentElement).toHaveClass("dark")
})

test("toggle switches to light and remembers", () => {
  toggleTheme()
  expect(getTheme()).toBe("light")
  expect(document.documentElement).not.toHaveClass("dark")
  resetThemeCache()
  expect(readTheme()).toBe("light")
  toggleTheme()
  expect(getTheme()).toBe("dark")
  expect(readTheme()).toBe("dark")
})

test("works when localStorage throws", () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked")
  })
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked")
  })
  expect(readTheme()).toBe("dark")
  expect(() => toggleTheme()).not.toThrow()
  expect(getTheme()).toBe("light")
})
