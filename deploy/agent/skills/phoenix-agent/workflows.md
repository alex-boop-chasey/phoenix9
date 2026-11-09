# What Alex may ask → what to run

Run `phoenix ... --help` for flags; the full list is in `commands.md`. Ask Alex first (confirm block) for
anything on the ask-first list in `SKILL.md`.

## New project
"Make me a project called X": `phoenix project templates` to see the choices, then
`phoenix project new X --template <t>` (ask first). Open it with a nav block to `p/X/overview`.

## Start a build
"Build the pricing page": the project needs a spec file (`phoenix spec check <file>`).
Then `phoenix run start <project> --spec <spec>` (ask first on a client project). Follow it with
`phoenix run status <run_id>` and a `run` card.

## Quick edit
"Change the footer text": `phoenix edit start <project> --title "<what>"`, work only in the folder it prints,
`phoenix edit heartbeat <id>` now and then, then `phoenix edit finish <id>`. Alex merges the request.

## Planning session
"Plan a contact form": `phoenix plan start <project> --brief "<what>"`; check `phoenix plan status <id>`
every few minutes. If it is `waiting`, show each question as a choice block and send his answer with
`phoenix plan reply <id> --text "<answer>"`. `done` means the spec is filed.

## Why did it fail
`phoenix repair report <run>`, then read `failures.md`. Show the fix as a `repair` card.

## Approve a merge
`phoenix gate list <project>`, `phoenix gate review <gate>` to read it to Alex, and only after his yes
`phoenix gate answer <gate> approve`. Never merge on your own.

## Update Phoenix
`phoenix update status` shows the installed and newest release. Installing needs Alex's yes:
`phoenix update install <tag> --yes --wait`. Roll back with `phoenix update rollback --yes`. `phoenix update log`
tells what happened. After an install Phoenix refreshes this knowledge pack and your rules by itself.

## Where is setting X
`phoenix settings explain <key>` says what it does; `phoenix settings show <project>` shows the value and
which layer set it; `settings.md` lists every key. Safety settings are Alex's alone (Settings page).

## Is everything healthy
`phoenix doctor`. Every line says what is wrong and the fix.
