import { Route, Routes } from "react-router"

import { AppShell } from "@/components/AppShell"
import GlobalSettingsPage from "@/pages/GlobalSettingsPage"
import ImportPage from "@/pages/ImportPage"
import NewProjectPage from "@/pages/NewProjectPage"
import NotFound from "@/pages/NotFound"
import ProjectPage from "@/pages/ProjectPage"
import ProjectsPage from "@/pages/ProjectsPage"
import StylesPage from "@/pages/StylesPage"

/** The route table for the whole app (the router itself is added in main.tsx). */
export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<ProjectsPage />} />
        <Route path="/new" element={<NewProjectPage />} />
        <Route path="/import" element={<ImportPage />} />
        <Route path="/styles" element={<StylesPage />} />
        <Route path="/p/:name" element={<ProjectPage />} />
        <Route path="/p/:name/:tab" element={<ProjectPage />} />
        <Route path="/settings" element={<GlobalSettingsPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </AppShell>
  )
}
