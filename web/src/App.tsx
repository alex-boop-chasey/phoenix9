import { Route, Routes } from "react-router"

import { ThemeToggle } from "@/components/ThemeToggle"
import GlobalSettings from "@/pages/GlobalSettings"
import NewProject from "@/pages/NewProject"
import NotFound from "@/pages/NotFound"
import ProjectPage from "@/pages/ProjectPage"
import Projects from "@/pages/Projects"

/** The route table for the whole app (the router itself is added in main.tsx). */
export default function App() {
  return (
    <>
      <div className="flex justify-end p-2">
        <ThemeToggle />
      </div>
      <Routes>
        <Route path="/" element={<Projects />} />
        <Route path="/new" element={<NewProject />} />
        <Route path="/p/:name" element={<ProjectPage />} />
        <Route path="/p/:name/:tab" element={<ProjectPage />} />
        <Route path="/settings" element={<GlobalSettings />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </>
  )
}
