import { Navigate, useParams } from "react-router"

const TABS = ["overview", "build", "logs", "settings"] as const

/** Placeholder project page: shows the title of the chosen tab (a later step fills it in). */
export default function ProjectPage() {
  const { name = "", tab } = useParams()
  if (!tab || !(TABS as readonly string[]).includes(tab)) {
    return <Navigate to={`/p/${name}/overview`} replace />
  }
  return (
    <main className="p-4">
      <h1 className="text-2xl font-semibold">{name}</h1>
      <p data-testid="tab" className="text-muted-foreground capitalize">
        {tab}
      </p>
    </main>
  )
}
