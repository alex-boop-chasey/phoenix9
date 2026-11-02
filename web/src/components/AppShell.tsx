import { Settings } from "lucide-react"
import type { ReactNode } from "react"
import { Link } from "react-router"

import { ThemeToggle } from "@/components/ThemeToggle"
import { Badge } from "@/components/ui/badge"
import { useInfo } from "@/lib/queries"

/** The header and page frame around every route. */
export function AppShell({ children }: { children: ReactNode }) {
  const { data: info } = useInfo()
  const update = info?.update
  return (
    <div className="min-h-screen overflow-x-hidden">
      <header className="border-b">
        <div className="mx-auto flex h-12 max-w-[1200px] items-center gap-2 px-4">
          <Link to="/" className="font-semibold">
            Phoenix
          </Link>
          {info && <span className="text-xs text-muted-foreground">{info.version}</span>}
          {update?.supported && update.available && (
            <a href="#/p/phoenix9/overview">
              <Badge>Update available</Badge>
            </a>
          )}
          <div className="ml-auto flex items-center gap-1">
            <Link
              to="/settings"
              aria-label="Settings"
              className="inline-flex h-9 items-center gap-1.5 rounded-md px-2 text-sm hover:bg-accent"
            >
              <Settings className="size-4" aria-hidden />
              <span className="hidden sm:inline">Settings</span>
            </Link>
            <ThemeToggle />
          </div>
        </div>
      </header>
      <div className="mx-auto max-w-[1200px] px-4 py-4">{children}</div>
    </div>
  )
}
