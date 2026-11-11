// The .env parser follows the O45 rules.
import { parseEnv } from "./envfile"

test("skips blanks and comments, strips export and quotes, splits at the first =", () => {
  const rows = parseEnv(`# note\n\nexport A_KEY="abc"\nB='x=y'\nC = plain \nbad line\n1X=no\nD=a=b\n`)
  expect(rows.map((r) => [r.name, r.value])).toEqual([["A_KEY", "abc"], ["B", "x=y"], ["C", "plain"], ["D", "a=b"]])
})

test("mismatched quotes are kept and CRLF lines work", () => {
  expect(parseEnv(`A="x'\r\nB=y\r\n`).map((r) => r.value)).toEqual([`"x'`, "y"])
})

test("only clearly public names are not secret", () => {
  const by = Object.fromEntries(parseEnv(["PUBLIC_A=1", "NEXT_PUBLIC_B=1", "API_URL=x", "APP_ID=1", "PORT=80", "DB_PORT=1", "FEATURE_ENABLED=1", "API_KEY=s", "TOKEN=s", "DATABASE_PASSWORD=s"].join("\n")).map((r) => [r.name, r.secret]))
  expect(by).toMatchObject({ PUBLIC_A: false, NEXT_PUBLIC_B: false, API_URL: false, APP_ID: false, PORT: false, DB_PORT: false, FEATURE_ENABLED: false, API_KEY: true, TOKEN: true, DATABASE_PASSWORD: true })
})
