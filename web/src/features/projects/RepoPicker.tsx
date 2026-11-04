// A searchable drop-down for choosing one of the connected GitHub account's repos.
import { useState } from "react"
import { Check, ChevronsUpDown } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command"
import { Label } from "@/components/ui/label"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"

export function RepoPicker({
  repos, value, onPick,
}: {
  repos: { full_name: string; owner: string; private: boolean }[]
  value: string
  onPick: (repo: string) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="space-y-2">
      <Label htmlFor="pf-repo">GitHub repo</Label>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button id="pf-repo" type="button" variant="outline" role="combobox" aria-expanded={open} className="w-full justify-between">
            {value || "Choose a repo"}
            <ChevronsUpDown className="opacity-50" aria-hidden />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[--radix-popover-trigger-width] p-0" align="start">
          <Command>
            <CommandInput placeholder="Search repos" />
            <CommandList>
              <CommandEmpty>No repo found.</CommandEmpty>
              {repos.map((r) => (
                <CommandItem key={r.full_name} value={r.full_name} onSelect={() => { onPick(r.full_name); setOpen(false) }}>
                  <Check className={value === r.full_name ? "opacity-100" : "opacity-0"} aria-hidden />
                  {r.full_name}
                  {r.private && <span className="ml-auto text-xs text-muted-foreground">private</span>}
                </CommandItem>
              ))}
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
    </div>
  )
}
