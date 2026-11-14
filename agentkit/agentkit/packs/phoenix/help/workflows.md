# What Alex may ask, and what to do

Every change tool shows Alex an approval card first. Choices go one at a time with `ask_choice`.

## New project

"Make me a project called X": check the name with `project-check-name`, read the choices with
`library-templates`, `library-profiles` and `library-services`, ask Alex each choice, then call `project-create`.
Follow it with `job-status` until it ends, and offer to open the project with `go_to`.

## Keys

Ask for one key with `ask_for_key`, or a whole .env file with `ask_env_file`. Alex types or picks it in his browser
and it goes straight to Phoenix. Never ask for a key in the chat. `keys-list` shows which names are set (never
values).

## Start a build

"Build the pricing page": the project needs a spec. Read the specs with `project-specs` and check the plan with
`build-plan`, then call `build-start` with the project, spec and preset Alex picked. Follow it with `run-show`
or `builds-list`.

## Small change

"Change the footer text": write a short brief (what and where, no code) and call `hotfix-start`. Only one hotfix
runs at a time per project.

## Quick edits

Project chats make quick edits in a branch copy. `edits-list` lists the open ones. `edit-finish` has Phoenix check
it and open a merge request (follow it with `job-status`); `edit-abandon` throws one away after Alex types its id.

## Planning session

"Plan a contact form": `plan-start` with a plain brief, then check it now and then with `plan-show`. Queued or
running means wait; waiting means it has questions. Read them with `docs-show` (the plan's spec id), show each one
to Alex with `ask_choice`, and send his answer word for word with `plan-reply`. Done means the spec is ready.
`plans-list` lists the sessions. Never start one on Phoenix itself.

## Why did it fail

Read the run with `run-diagnose` and `task-tries`, explain it with `what_happened`, then read the failures topic
and offer the repairs.

## Approve a merge

`gates-list` shows the build's questions and `gate-review` everything Alex needs to read a merge. Read it to him,
and only after his yes call `merge-answer` (approve, send back or skip). Never merge on your own.

## Update Phoenix

`update-check` says whether a newer Phoenix is out. Installing needs Alex's yes: `update-install`. Rolling back
is done from the dashboard (Phoenix settings, updates).

## Where is setting X

`settings-explain` says in plain English what a project's settings do, `settings-show` shows each value and where
it came from, and the settings topic lists every key. Safety settings are Alex's alone (the project's Settings
page).

## Is everything healthy

`doctor-run`: every line says what is wrong and the fix. `services-list` shows which services are connected.

## Project chats

`chat-show` says whether a project's chat is awake or asleep, `chat-open` opens and wakes it, `chat-sleep` puts it
to sleep (nothing is lost), and `chat-forget` makes Chat start a fresh one (Alex types the project name).
