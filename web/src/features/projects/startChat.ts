// "Start chat": start the project's chat, then ask again until its link shows up.
import { toast } from "sonner"

import { api } from "@/lib/api"

const TRIES = 8
const WAIT_MS = 1500

const pause = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** Start the chat for a project and tell the user when its link is ready (or that it is starting). */
export async function startChat(name: string, refresh: () => void, wait = WAIT_MS): Promise<void> {
  const id = toast.loading(`Starting the chat for ${name}…`)
  try {
    let chat = (await api.chatStart(name)).chat
    for (let i = 0; !chat.url && i < TRIES; i++) {
      await pause(wait)
      chat = (await api.project(name)).chat
    }
    refresh()
    if (chat.url) {
      const url = chat.url
      toast.success(`Chat for ${name} is on`, { id, action: { label: "Open chat", onClick: () => window.open(url, "_blank", "noreferrer") } })
    } else {
      toast.info(`Chat for ${name} is starting`, { id, description: "Its link isn't ready yet. Try again in a moment." })
    }
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "The chat could not be started.", { id })
  }
}
