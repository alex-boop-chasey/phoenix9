import { Link } from "react-router"

/** Shown for any address the app does not know. */
export default function NotFound() {
  return (
    <main className="p-4">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <Link to="/" className="text-primary underline">
        Back to projects
      </Link>
    </main>
  )
}
