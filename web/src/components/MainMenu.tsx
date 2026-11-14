import { Link, useLocation } from "react-router"

import { Icon, type IconName } from "@/components/Icon"

interface MenuItem {
  label: string
  to: string
  icon: IconName
  /** Whether this item is the current section for a path. */
  current: (pathname: string) => boolean
}

/** The main menu items, left to right. Later sections (Version Control, Image Studio, ...) go here. */
export const MENU: MenuItem[] = [
  {
    label: "Projects",
    to: "/",
    icon: "squares-four",
    current: (p) => p === "/" || p.startsWith("/p/") || p === "/new" || p === "/import",
  },
]

/** The main menu in the top bar, starting at the left edge of the page area (not beside the logo). */
export function MainMenu() {
  const { pathname } = useLocation()
  return (
    <nav className="mainmenu" aria-label="Main menu">
      {MENU.map((m) => (
        <Link key={m.to} className="mm-item" to={m.to} aria-current={m.current(pathname) ? "page" : undefined}>
          <Icon name={m.icon} size="sm" />
          {m.label}
        </Link>
      ))}
    </nav>
  )
}
