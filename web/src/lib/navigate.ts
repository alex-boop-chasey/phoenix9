// Moving the dashboard from the Agent drawer without closing the drawer.

/** Go to a dashboard hash such as "#/settings?section=models"; the panel's open state is not touched. */
export function navigateKeepingPanel(hash: string): void {
  const next = hash.startsWith("#") ? hash : `#/${hash.replace(/^\//, "")}`
  if (window.location.hash !== next) window.location.hash = next
}
