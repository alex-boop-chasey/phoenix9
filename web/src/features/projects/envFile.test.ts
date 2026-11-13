import { isPublicKey, parseEnvFile, skippedNote } from "@/features/projects/envFile"

test("plain lines, comments and blank lines", () => {
  const got = parseEnvFile("# a comment\n\nAPI_KEY=abc\n   # indented comment\nPORT=3000\n")
  expect(got).toEqual({
    entries: [
      { name: "API_KEY", value: "abc", secret: true },
      { name: "PORT", value: "3000", secret: false },
    ],
    skipped: 0,
  })
})

test("export prefix and surrounding quotes", () => {
  const got = parseEnvFile(`export TOKEN="s3 cret"\nexport  SINGLE='x'\nMIXED="a'\nINNER=a"b"c`)
  expect(got.entries.map((e) => [e.name, e.value])).toEqual([
    ["TOKEN", "s3 cret"], ["SINGLE", "x"], ["MIXED", `"a'`], ["INNER", `a"b"c`],
  ])
})

test("CRLF line ends", () => {
  const got = parseEnvFile("A=1\r\nB=2\r\n")
  expect(got.entries.map((e) => [e.name, e.value])).toEqual([["A", "1"], ["B", "2"]])
  expect(got.skipped).toBe(0)
})

test("= inside the value is kept", () => {
  const got = parseEnvFile("DATABASE_DSN=postgres://u:p@h/db?a=b&c=d\nB64=abc==")
  expect(got.entries.map((e) => e.value)).toEqual(["postgres://u:p@h/db?a=b&c=d", "abc=="])
})

test("empty value is kept as an empty row", () => {
  expect(parseEnvFile("EMPTY=\nQUOTED=\"\"").entries).toEqual([
    { name: "EMPTY", value: "", secret: true },
    { name: "QUOTED", value: "", secret: true },
  ])
})

test("bad lines are counted", () => {
  const got = parseEnvFile("just words\n1BAD=x\n=nothing\nGOOD=1\nexport")
  expect(got.entries.map((e) => e.name)).toEqual(["GOOD"])
  expect(got.skipped).toBe(4)
  expect(skippedNote(got.skipped)).toBe("4 lines were skipped: not KEY=value")
  expect(skippedNote(1)).toBe("1 line was skipped: not KEY=value")
  expect(skippedNote(0)).toBe("")
})

test("a repeated name keeps the later value once", () => {
  expect(parseEnvFile("A=1\nB=2\nA=3").entries.map((e) => [e.name, e.value])).toEqual([["B", "2"], ["A", "3"]])
})

test("public-name rule: secret unless clearly public", () => {
  for (const name of ["PUBLIC_SITE", "NEXT_PUBLIC_KEY", "VITE_API", "EXPO_PUBLIC_X", "SITE_URL", "CLIENT_ID", "PORT"]) {
    expect(isPublicKey(name, "x")).toBe(true)
  }
  for (const name of ["API_KEY", "CLIENT_SECRET_ID", "STRIPE_SECRET", "PORTS", "MY_PORT", "SECRET", "PUBLICKEY"]) {
    expect(isPublicKey(name, "x")).toBe(false)
  }
  expect(isPublicKey("DEBUG", "true")).toBe(true)
  expect(isPublicKey("FEATURE", "False")).toBe(true)
  expect(isPublicKey("FEATURE", "yes")).toBe(false)
})
