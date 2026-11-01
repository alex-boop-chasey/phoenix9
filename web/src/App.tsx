import { Route, Routes } from "react-router"

import { AppShell } from "@/components/AppShell"
import GlobalSettings from "@/pages/GlobalSettings"
import NewProject from "@/pages/NewProject"
import NotFound from "@/pages/NotFound"
import ProjectPage from "@/pages/ProjectPage"
import ProjectsPage from "@/pages/ProjectsPage"

/** The route table for the whole app (the router itself is added in main.tsx). */
export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<ProjectsPage />} />
        <Route path="/new" element={<NewProject />} />
        <Route path="/p/:name" element={<ProjectPage />} />
        <Route path="/p/:name/:tab" element={<ProjectPage />} />
        <Route path="/settings" element={<GlobalSettings />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </AppShell>
  )
}
