// A token paste box for connecting GitHub; shown only when the server says it can (never echoes the value).
import { useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { post } from "@/lib/api"
import { keys } from "@/lib/queries"

/** Password input plus Save; the token goes to the listed endpoint and is cleared at once. */
export function GithubConnectForm({ endpoint }: { endpoint: string }) {
  const qc = useQueryClient()
  const [token, setToken] = useState("")
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    try {
      await post(endpoint, { token })
      setToken("")
      toast.success("GitHub connected.")
      void qc.invalidateQueries({ queryKey: keys.global() })
      void qc.invalidateQueries({ queryKey: keys.info() })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Could not connect GitHub.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(e) => { e.preventDefault(); void save() }}
    >
      <Input
        type="password"
        autoComplete="off"
        aria-label="GitHub token"
        className="max-w-sm"
        value={token}
        onChange={(e) => setToken(e.target.value)}
      />
      <Button type="submit" disabled={!token || busy}>Save</Button>
    </form>
  )
}
