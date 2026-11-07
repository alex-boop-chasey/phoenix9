import { chatLink, isPhone } from "@/lib/chatLink"

const DESKTOP = "Mozilla/5.0 (X11; Linux x86_64) Chrome/120"
const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)"
const ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) Mobile"

test("phones are told apart from desktops", () => {
  expect(isPhone(DESKTOP)).toBe(false)
  expect(isPhone(IPHONE)).toBe(true)
  expect(isPhone(ANDROID)).toBe(true)
  expect(isPhone("Mozilla/5.0 (iPad; CPU OS 17_0)")).toBe(true)
})

test("desktop gets the app link, phones the web link", () => {
  expect(chatLink("abc", DESKTOP)).toBe("claude://claude.ai/code/abc")
  expect(chatLink("abc", IPHONE)).toBe("https://claude.ai/code/abc")
})
