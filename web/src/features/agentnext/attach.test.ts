// The attachment helper: picture resize maths, which files may go, the plain limit messages and upload answers.
import {
  ACCEPT, EMPTY, MAX_FILE, MAX_SIDE, TOO_BIG, TOO_MANY, WRONG_TYPE, attachmentsOf, checkFile, fitSize, hasTransparency,
  kindOf, needsRedraw, outputType, refusalWords, renamed, shrinkImage, sizeWords, toBase64,
} from "./attach"

const file = (name: string, type: string, size = 100) => ({ name, type, size })

describe("fitSize", () => {
  it("keeps pictures that already fit", () => {
    expect(fitSize(800, 600)).toEqual({ width: 800, height: 600 })
    expect(fitSize(MAX_SIDE, 10)).toEqual({ width: MAX_SIDE, height: 10 })
  })
  it("shrinks the longest side to 1568 and keeps the shape", () => {
    expect(fitSize(3136, 2000)).toEqual({ width: 1568, height: 1000 })
    expect(fitSize(1000, 4000)).toEqual({ width: 392, height: 1568 })
    expect(fitSize(4032, 3024)).toEqual({ width: 1568, height: 1176 })
  })
  it("never makes a side zero", () => {
    expect(fitSize(100000, 10)).toEqual({ width: 1568, height: 1 })
  })
})

describe("what a picture is saved as", () => {
  it("JPEG unless a PNG has see-through parts; GIFs are left alone", () => {
    expect(outputType("image/png", true)).toBe("image/png")
    expect(outputType("image/png", false)).toBe("image/jpeg")
    expect(outputType("image/jpeg", false)).toBe("image/jpeg")
    expect(outputType("image/webp", true)).toBe("image/jpeg")
    expect(outputType("image/gif", true)).toBeNull()
  })
  it("redraws big pictures and PNGs, never GIFs or other files", () => {
    expect(needsRedraw("image/jpeg", 4000, 3000)).toBe(true)
    expect(needsRedraw("image/jpeg", 800, 600)).toBe(false)
    expect(needsRedraw("image/png", 800, 600)).toBe(true)
    expect(needsRedraw("image/gif", 4000, 3000)).toBe(false)
    expect(needsRedraw("application/pdf", 4000, 3000)).toBe(false)
  })
  it("renames a file whose type changed", () => {
    expect(renamed("Screen Shot.png", "image/jpeg")).toBe("Screen Shot.jpg")
    expect(renamed("photo.webp", "image/jpeg")).toBe("photo.jpg")
    expect(renamed(".png", "image/jpeg")).toBe("picture.jpg")
  })
  it("finds transparency in RGBA data", () => {
    expect(hasTransparency([1, 2, 3, 255, 4, 5, 6, 255])).toBe(false)
    expect(hasTransparency([1, 2, 3, 255, 4, 5, 6, 0])).toBe(true)
  })
  it("keeps files it cannot draw (no canvas here) as they are", async () => {
    const f = new File(["abc"], "a.txt", { type: "text/plain" })
    expect(await shrinkImage(f)).toBe(f)
    const gif = new File(["GIF89a"], "a.gif", { type: "image/gif" })
    expect(await shrinkImage(gif)).toBe(gif)
  })
})

describe("which files may go", () => {
  it("knows pictures, PDFs and text files by type or name", () => {
    expect(kindOf(file("a.png", "image/png"))).toBe("image")
    expect(kindOf(file("a.heic", "image/heic"))).toBeNull()
    expect(kindOf(file("a.pdf", "application/pdf"))).toBe("pdf")
    expect(kindOf(file("notes.md", ""))).toBe("text")
    expect(kindOf(file("config.yaml", "application/x-yaml"))).toBe("text")
    expect(kindOf(file("run.log", "application/octet-stream"))).toBe("text")
    expect(kindOf(file("data.json", "application/json"))).toBe("text")
    expect(kindOf(file("tool.exe", "application/x-msdownload"))).toBeNull()
    expect(kindOf(file("archive.zip", "application/zip"))).toBeNull()
  })
  it("says plainly why a file can't go", () => {
    expect(checkFile(file("a.png", "image/png"), 0)).toBeNull()
    expect(checkFile(file("a.png", "image/png", MAX_FILE), 4)).toBeNull()
    expect(checkFile(file("a.png", "image/png", MAX_FILE + 1), 0)).toBe(TOO_BIG)
    expect(checkFile(file("a.png", "image/png"), 5)).toBe(TOO_MANY)
    expect(checkFile(file("a.zip", "application/zip"), 0)).toBe(WRONG_TYPE)
    expect(checkFile(file("a.txt", "text/plain", 0), 0)).toBe(EMPTY)
    expect(TOO_BIG).toBe("That file is too big to attach (at most 10 MB).")
    expect(TOO_MANY).toBe("At most 5 files can go with one message.")
  })
  it("offers pictures (and so the phone camera), PDFs and the text types in the picker", () => {
    expect(ACCEPT).toBe("image/*,application/pdf,.txt,.md,.csv,.json,.yaml,.yml,.toml,.log")
  })
})

describe("words and answers", () => {
  it("says sizes in short words", () => {
    expect(sizeWords(512)).toBe("512 bytes")
    expect(sizeWords(340 * 1024)).toBe("340 KB")
    expect(sizeWords(1.25 * 1024 * 1024)).toBe("1.3 MB")
  })
  it("shows the service's plain refusal, Phoenix's message, or a general line, never an internal word", () => {
    expect(refusalWords({ error: "That file is empty." })).toBe("That file is empty.")
    expect(refusalWords({ ok: false, message: "The request was too big." })).toBe("The request was too big.")
    expect(refusalWords({ error: "no such thread" })).toBe("The file could not be attached. Try again.")
    expect(refusalWords(null)).toBe("The file could not be attached. Try again.")
  })
  it("turns bytes into base64", async () => {
    expect(await toBase64(new Blob(["hello"]))).toBe("aGVsbG8=")
  })
  it("reads only well-formed attachments from a stored message", () => {
    const ok = { id: "a1", name: "shot.png", mime: "image/png", size: 10 }
    expect(attachmentsOf({ text: "x", attachments: [ok, { id: 3 }, null] })).toEqual([ok])
    expect(attachmentsOf({ text: "x" })).toEqual([])
  })
})
