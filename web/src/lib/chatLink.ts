// Which link opens a chat conversation: the desktop app or the phone browser.

/** True for phones and tablets (iPhone, iPad, Android, Mobile). */
export function isPhone(userAgent: string): boolean {
  return /iPhone|iPad|Android|Mobile/i.test(userAgent)
}

/** The link for a conversation: the app link on desktop, the web link on phones. */
export function chatLink(id: string, userAgent: string): string {
  const scheme = isPhone(userAgent) ? "https" : "claude"
  return `${scheme}://claude.ai/code/${id}`
}
