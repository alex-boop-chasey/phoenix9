/// <reference types="node" />
// Every agent tool has plain words for the "Working…" line, and none of them shows a tool id.
import { readdirSync, readFileSync, statSync } from "node:fs"
import { join } from "node:path"

import { TOOL_WORDS, toolWords } from "./toolWords"

const AGENTKIT = join(process.cwd(), "..", "agentkit", "agentkit")   // vitest runs in web/

function pythonFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f)
    return statSync(p).isDirectory() ? pythonFiles(p) : f.endsWith(".py") ? [p] : []
  })
}

/** Phoenix controls the agent may call, read from the generated controls.json. */
function controlTools(): string[] {
  const list = JSON.parse(readFileSync(join(AGENTKIT, "packs", "phoenix", "controls.json"), "utf8")) as { name: string; agent: string }[]
  return list.filter((c) => c.agent === "tool").map((c) => c.name)
}

/** The agent's own tools: every ServerTool("x"), BrowserTool("x") and SUGGEST = "x" in the agentkit source. */
function agentkitTools(): string[] {
  const names = new Set<string>()
  for (const f of pythonFiles(AGENTKIT)) {
    const text = readFileSync(f, "utf8")
    for (const m of text.matchAll(/(?:ServerTool|BrowserTool)\("([^"]+)"|SUGGEST = "([^"]+)"/g)) names.add(m[1] ?? m[2]!)
  }
  return [...names]
}

test("the sources list the tools we expect to cover", () => {
  expect(controlTools()).toEqual(expect.arrayContaining(["library-profiles", "projects-list", "build-start"]))
  expect(agentkitTools()).toEqual(expect.arrayContaining(["go_to", "suggest_next_actions", "phoenix_help"]))
})

test("every agent tool and agentkit tool has plain words", () => {
  const missing = [...controlTools(), ...agentkitTools()].filter((n) => !(n in TOOL_WORDS))
  expect(missing).toEqual([])
})

test("no entry's words contain an id", () => {
  const bad = Object.entries(TOOL_WORDS).filter(([, w]) => /[-_]/.test(w.doing + w.done)).map(([n]) => n)
  expect(bad).toEqual([])
})

test("words are sentence case", () => {
  for (const w of Object.values(TOOL_WORDS)) {
    for (const t of [w.doing, w.done]) expect(t[0]).toBe(t[0]!.toUpperCase())
  }
})

test("the step's examples read as asked", () => {
  expect(toolWords("library-profiles")).toEqual({ doing: "Checking project types", done: "Checked project types" })
  expect(toolWords("projects-list")).toEqual({ doing: "Looking at your projects", done: "Looked at your projects" })
  expect(toolWords("suggest_next_actions")).toEqual({ doing: "Thinking of next steps", done: "Suggested next steps" })
  expect(toolWords("build-start")).toEqual({ doing: "Starting a build", done: "Started a build" })
})

test("an unknown tool gets general words, never its id", () => {
  expect(toolWords("brand-new_tool")).toEqual({ doing: "Working", done: "Done a step" })
  expect(toolWords("constructor")).toEqual({ doing: "Working", done: "Done a step" })
})
