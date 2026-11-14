import type { Gate, UnlockUsed } from "@/lib/types"

/** The repairs Alex can allow once, in plain words; keep in step with phoenix9/repair/unlock.py UNLOCKS. */
const WORDS: Record<string, string> = {
  "replace-spec": "replace the spec",
  "keep-hand-fix": "keep a hand fix",
  "reset-worktree": "reset the worktree",
  force: "force a repair past its check",
  "unlock-checks": "unlock locked checks",
  stop: "stop the run",
  discard: "discard the run's work",
}

/** One repair in plain words (an unknown name as it is). */
export const unlockWord = (name: string) => WORDS[name] ?? name

/** The repairs in plain words: "reset the worktree and replace the spec". */
export function unlockList(names: string[]): string {
  const words = names.map(unlockWord)
  return words.length <= 1 ? (words[0] ?? "") : `${words.slice(0, -1).join(", ")} and ${words.at(-1)}`
}

/** Who asked, in words: "The Phoenix agent" or "A chat in <project>". */
export function askerText(gate: Gate): string {
  const who = gate.asked_by ?? ""
  if (who.startsWith("chat:")) return who === "chat:home" ? "A chat on the home page" : `A chat in ${who.slice(5)}`
  return "The Phoenix agent"
}

/** "14:02" in Alex's own time; the text as it came when it is not a time. */
function clock(iso: string): string {
  const t = new Date(iso)
  if (Number.isNaN(t.getTime())) return iso
  return `${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`
}

/** The run page line for a used grant: "Repaired by the agent with your approval, 14:02: reset the worktree". */
export function unlockUsedText(used: UnlockUsed): string {
  return `Repaired by the agent with your approval, ${clock(used.at)}: ${unlockList(used.steps)}`
}
