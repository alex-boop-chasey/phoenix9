import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { HashRouter } from "react-router"

import App from "@/App"
import { ErrorBoundary } from "@/components/ErrorBoundary"
import { Toaster } from "@/components/ui/sonner"
import { applyTheme, getTheme } from "@/lib/theme"
import "./index.css"

// Under /proxy/<port> relative URLs only work when the path ends with "/".
const { pathname, search, hash } = location
if (!pathname.endsWith("/") && !/\.[^/]+$/.test(pathname)) {
  location.replace(pathname + "/" + search + hash)
} else {
  applyTheme(getTheme())
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } },
  })
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <ErrorBoundary>
          <HashRouter>
            <App />
          </HashRouter>
        </ErrorBoundary>
        <Toaster />
      </QueryClientProvider>
    </StrictMode>,
  )
}
