// Make text the panel sends to the agent one line, so a label can never start a line that looks like a panel answer.

const BREAKS = new RegExp("[\\u0000-\\u001f\\u007f-\\u009f\\u2028\\u2029]+", "g")

/** The text with every run of control characters, line or paragraph separators turned into one space, trimmed. */
export function oneLine(text: string): string {
  return text.replace(BREAKS, " ").replace(/ {2,}/g, " ").trim()
}
