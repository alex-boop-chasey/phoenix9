import { Component, type ErrorInfo, type ReactNode } from "react"

import { Button } from "@/components/ui/button"

interface State {
  error: Error | null
}

interface Props {
  children: ReactNode
  /** When this changes (the page address) a shown error clears, without remounting a healthy page. */
  resetKey?: string
}

/** Catches a crash in the part of the dashboard it wraps and shows a plain message instead of a blank screen. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: unknown): State {
    return { error: error instanceof Error ? error : new Error(String(error)) }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error("Dashboard error", error, info.componentStack)
  }

  componentDidUpdate(prev: Props) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.reset()
  }

  reset = () => this.setState({ error: null })

  home = () => {
    window.location.hash = "#/"
    this.reset()
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div role="alert" className="flex flex-col items-center gap-3 rounded-lg border border-destructive/40 p-8 text-center">
        <p>This part of the dashboard hit a problem.</p>
        {error.message && <p className="text-xs text-muted-foreground break-words">{error.message}</p>}
        <div className="flex flex-wrap justify-center gap-2">
          <Button variant="outline" className="min-h-11" onClick={this.reset}>Try again</Button>
          <Button variant="ghost" className="min-h-11" onClick={this.home}>Back to projects</Button>
        </div>
      </div>
    )
  }
}
