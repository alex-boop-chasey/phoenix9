<!-- phoenix 9.1.0 inputs 7d3596465d109b29 -->
# Phoenix commands

Every command takes `--json` (machine-readable answer) and `--who NAME` (who is running it).
Destructive commands need `--yes`.

## `phoenix run`

start, watch and stop builds

### `phoenix run start`

queue a run of a spec file

- `<project>`
- `--spec SPEC`: the spec file
- `--preset PRESET`: use this preset for this run only

### `phoenix run status`

show how a run is going

- `<run_id>`
- `--watch`: keep printing new events until the run stops

### `phoenix run list`

list runs, newest first

- `<project>`

### `phoenix run log`

show a run's events and logs

- `<run_id>`
- `--step STEP`
- `--task TASK`
- `--summary`: print the run's summary.md

### `phoenix run stop`

stop a run and remove its containers

- `<run_id>`
- `--yes`: confirm that you mean it

### `phoenix run pause`

pause the step that is running now (the worktree stays as it is)

- `<run_id>`
- `--now`: pause the running step right now
- `--yes`: confirm that you mean it

### `phoenix run resume`

carry on a paused run where it stopped

- `<run_id>`

### `phoenix run note`

add a note to a task; its next attempt reads it

- `<run_id>`
- `<task>`
- `<text>`: the note (at most 2,000 characters)

### `phoenix run discard`

throw away a failed or stopped run's worktree and branch (here and on GitHub)

- `<run_id>`
- `--yes`: confirm that you mean it
- `--force`: also when the run has an open merge request or commits not on main (that work is lost)

## `phoenix gate`

questions waiting for you

### `phoenix gate list`

list open questions

- `<project>`

### `phoenix gate review`

read a merge before answering

- `<gate_id>`

### `phoenix gate answer`

answer a question

- `<gate_id>`
- `<answer>`
- `--note NOTE` (default ): words for the step (needed for 'back')
- `--by BY`: dollars to add to the cap (for 'raise')

## `phoenix settings`

a project's settings

### `phoenix settings show`

every setting and where it came from

- `<project>`

### `phoenix settings explain`

the plan in plain words

- `<project>`

### `phoenix settings check`

look for mistakes in phoenix.toml

- `<project>`

### `phoenix settings set`

change one setting

- `<project>`
- `<key=value>`

### `phoenix settings add`

add one item to a list setting (safety_files, services...)

- `<project>`
- `<key>`: a list setting, e.g. safety_files
- `<item>`

### `phoenix settings remove`

take one item out of a list setting

- `<project>`
- `<key>`: a list setting, e.g. safety_files
- `<item>`

### `phoenix settings preset`

choose a preset

- `<project>`
- `<name>`

### `phoenix settings global`

Phoenix's own settings (dashboard addresses)

#### `phoenix settings global show`

the dashboard addresses

#### `phoenix settings global set`

set dashboard_url, allowed_origins (comma list) or vscode_url (empty = not set)

- `<key=value>`

#### `phoenix settings global migrate`

one time: allowed_origins = api.env's origins + the dashboard's (nothing once set)

## `phoenix steps`

the build steps

### `phoenix steps list`

list steps

## `phoenix profiles`

project profiles

### `phoenix profiles list`

list profiles

## `phoenix presets`

presets

### `phoenix presets list`

list presets

## `phoenix project`

projects

### `phoenix project list`

list projects, optionally searched and filtered

- `--filter TEXT` (default ): only projects whose name or description has this text
- `--status STATUS` (default all): all, run, fail, idle or need
- `--owner OWNER` (default all): all, none (no repo) or a GitHub owner
- `--sort SORT` (default name): name, active, size, created or modified
- `--attention`: put projects that need you first
- `--all`: also list the Phoenix agent's own folder

### `phoenix project show`

show one project

- `<name>`

### `phoenix project edit`

change a project's description, profile or repo

- `<name>`
- `--description TEXT`
- `--profile PROFILE`
- `--repo O/N`

### `phoenix project remove`

take a project off Phoenix's list (keeps every file)

- `<name>`
- `--yes`: really remove it

### `phoenix project delete`

delete a project entirely (--dry-run shows what would go)

- `<name>`
- `--dry-run`: show what would be deleted; change nothing
- `--confirm NAME`: the project's name, typed again, to really delete it

### `phoenix project delete-repo`

retry deleting the GitHub repo of a deleted project

- `<name>`

### `phoenix project import`

bring a removed project or an existing folder into Phoenix

- `<NAME|PATH>`
- `--list`: list what can be imported

### `phoenix project check-files`

add any missing memory files (never overwrites)

- `<NAME>`
- `--all`: check every project

### `phoenix project new`

create a project

- `<name>`
- `--description TEXT` (default )
- `--profile PROFILE`
- `--template T`: a menu template (see: phoenix project templates) or a GitHub OWNER/NAME
- `--repo O/N`: copy this GitHub repo into code/
- `--code PATH`: use code that already lives in this folder
- `--new-repo OWNER`: make a private GitHub repo under OWNER
- `--no-new-repo`: do not make a GitHub repo
- `--services A,B` (default )
- `--keys-file PATH`: a TOML file of [[key]] name/value/secret rows

### `phoenix project templates`

the templates menu

### `phoenix project keys`

a project's keys (secret values are never shown)

- `<name>`
- `<action>`
- `<NAME>`
- `--secret`: with set: the value is secret
- `--from-file PATH`: with set: read the value from this file (else stdin)
- `--yes`: with remove: really delete

### `phoenix project services`

a project's services

- `<name>`
- `--set A,B`: choose these services (empty text for none)

## `phoenix doctor`

check this installation

- `--quick`: only the cheap checks (services, API, home, secrets, disk)
- `--for-update`: the checks an update needs (no Claude session)

## `phoenix api`

the dashboard API

### `phoenix api serve`

run the dashboard API until stopped

- `--port PORT` (default 8090)
- `--host HOST` (default 127.0.0.1): 127.0.0.1 or localhost only

## `phoenix service`

Phoenix's own services (phoenix-api, phoenix-runner)

### `phoenix service restart`

restart api or runner (the runner waits for builds to reach a task boundary)

- `<name>`: api or runner
- `--yes`: confirm that you mean it

## `phoenix services`

connected services (Supabase, Stripe...)

### `phoenix services list`

every service and whether it is connected

### `phoenix services connect`

save a service's account keys and check them

- `<name>`
- `--from-file PATH`: read NAME=value lines from this file
- `--from-stdin`: read NAME=value lines from stdin
- `--no-check`: save without trying the key

### `phoenix services test`

try a connected service's saved key

- `<name>`

### `phoenix services disconnect`

remove a service's account keys

- `<name>`
- `--yes`: confirm

### `phoenix services recipes`

what the library holds for each service

## `phoenix keys`

account and project keys audit

### `phoenix keys audit`

which keys exist, where they are used, and problems

## `phoenix update`

update Phoenix 9 itself

### `phoenix update status`

installed and newest version

- `--refresh`: ask GitHub for the newest version

### `phoenix update install`

install a version (default: the newest)

- `<tag>`: a release tag like v9.2
- `--yes`: go ahead
- `--wait`: wait until the update is finished

### `phoenix update rollback`

go back to the previous version

- `--yes`: go ahead
- `--wait`: wait until the rollback is finished

### `phoenix update log`

the updater log

- `--lines LINES` (default 200)

### `phoenix update release`

tag the current main as a new release

- `--yes`: go ahead

## `phoenix deploy`

deploy a project

### `phoenix deploy now`

deploy the project's main code now

- `<project>`
- `--yes`: go ahead

### `phoenix deploy status`

last deploys, live address, last good commit

- `<project>`

## `phoenix deployers`

the deployers library

### `phoenix deployers list`

list deployers

## `phoenix images`

step images

### `phoenix images build`

build the step images

- `--profile P` (default []): build this profile (repeatable; 'base' builds the base image)
- `--all`: every profile and the base image
- `--changed`: only images whose files changed since they were built

## `phoenix models`

Phoenix's default models for the AI steps

### `phoenix models list`

each AI step's model and fallbacks

### `phoenix models set`

choose the default model for one AI step

- `<step>`
- `<model>`
- `--fallback MODEL` (default []): a fallback model; up to two

## `phoenix agent`

the Phoenix agent chat: brief, status, send, read

### `phoenix agent brief`

short summary of all projects for the agent

### `phoenix agent status`

is the agent awake, busy or idle

### `phoenix agent send`

post a message to the agent

- `<text>`: the message
- `--page PAGE`: the panel page this is about
- `--project PROJECT`: the project this is about
- `--run RUN`: the run this is about

### `phoenix agent read`

read the agent's conversation as plain lines

- `--after AFTER`: only items after this line number
- `--tail TAIL`: only the last N items

### `phoenix agent restart`

restart the agent's service (needs --yes)

- `--yes`: confirm that you mean it

### `phoenix agent watch`

check once that the agent is running; restart it if not

## `phoenix block`

check reply blocks

### `phoenix block check`

check one block (a fenced block or bare JSON)

- `<file>`: a file holding the block, or - for standard input
- `--kind KIND`: the block kind (needed for bare JSON)

## `phoenix choice`

make a phoenix-choice block for the agent to paste

- `--id ID`: a short id, like pick-db
- `--question QUESTION`: the question to ask
- `--option KEY=LABEL[::DETAIL]` (default []): an answer, repeatable (2 to 8)
- `--mode MODE` (default single): pick one or several
- `--recommended KEY`: the key of the option to suggest
- `--other`: also allow a free-text answer

## `phoenix confirm`

make a phoenix-confirm block for the agent to paste

- `--id ID`: a short id, like del-old
- `--action ACTION`: what will happen, in plain words
- `--command COMMAND`: the command that runs on yes
- `--danger`: mark the action as risky

## `phoenix card`

make a reply block (card) for the agent to paste

- `<type>`: the card type: projects, gates, run or builds
- `--query QUERY`: the card's query as a JSON object
- `--title TITLE`: a title to show instead of the default

## `phoenix doc`

read run and notes documents

### `phoenix doc show`

print a document

- `<id>`: the document id, like run:<run id>/plan.md or notes:<project>/<file>.md

### `phoenix doc list`

list a run's documents

- `<run>`: the run id

## `phoenix docs`

generate the agent's reference files

### `phoenix docs generate`

write commands, settings, steps, pages and cards files

- `--out OUT`: the folder to write into (default: the phoenix-agent skill folder)

## `phoenix nav`

make a link to a dashboard page for the agent to paste

- `<to>`: the page, like projects, new, settings or p/<name>/build
- `--param K=V` (default []): a page option, repeatable
- `--check`: only check the page exists: print ok or the reason

## `phoenix ui`

move the open dashboard

### `phoenix ui go`

move the dashboard to a page

- `<to>`: the page, like projects, new, settings or p/<name>/build
- `--param K=V` (default []): a page option, repeatable

## `phoenix chat`

project chats: open, sleep, off

### `phoenix chat open`

open (start if needed) a project's chat

- `<project>`: the project

### `phoenix chat sleep`

ask the chat to wrap up, then let it sleep

- `<project>`: the project

### `phoenix chat off`

stop and disable a project's chat (needs --yes)

- `<project>`: the project
- `--yes`: confirm that you mean it

### `phoenix chat catch-up`

set up chats for existing projects that have none

- `--all`: really do it (without it, only list what would be done)

## `phoenix repair`

look into a run that went wrong and put it right

### `phoenix repair check`

look for problems in a run

- `<run_id>`
- `--project PROJECT`: the project of the run (the run id alone is enough)

### `phoenix repair report`

write and show the plain-English report of a run

- `<run_id>`
- `--project PROJECT`: the project of the run (the run id alone is enough)

### `phoenix repair apply`

apply a repair note (snapshot, steps, check, roll back if bad)

- `<note>`: the repair note (a markdown file)
- `--dry-run`: only show what it would do; change nothing
- `--approve-unlock`: allow steps that unlock locked checks
- `--yes`: confirm that you mean it

### `phoenix repair undo`

undo a repair (default: the newest snapshot)

- `<run_id>`
- `--project PROJECT`: the project of the run (the run id alone is enough)
- `--to TO`: the snapshot number to go back to
- `--yes`: confirm that you mean it

### `phoenix repair resume`

let the runner carry on with a repaired run

- `<run_id>`
- `--project PROJECT`: the project of the run (the run id alone is enough)
- `--yes`: confirm that you mean it

## `phoenix edit`

quick edits in a branch copy of a project

### `phoenix edit start`

start a quick edit and print its folder

- `<project>`
- `--title TITLE`: what the edit is for

### `phoenix edit list`

list quick edits

- `--project PROJECT`: only this project

### `phoenix edit heartbeat`

say work is going on in a quick edit

- `<id>`

### `phoenix edit abandon`

remove a quick edit's folder and branch

- `<id>`
- `--yes`: confirm (this throws the work away)

### `phoenix edit finish`

check a quick edit, push it and open a merge request

- `<id>`
- `--message MESSAGE`: the commit message (default: the edit's title)

## `phoenix plan`

planning sessions that write a spec for a project

### `phoenix plan start`

queue a planning session (the runner service runs it; poll `phoenix plan status`)

- `<project>`
- `--brief BRIEF`: what to plan
- `--model MODEL`: the model (default: setting plan.model)

### `phoenix plan status`

show one planning session

- `<id>`

### `phoenix plan continue`

queue the session again after the answers are filled in

- `<id>`

### `phoenix plan reply`

queue Alex's answer for a waiting session

- `<id>`
- `--text TEXT`: the answer, word for word

### `phoenix plan abandon`

give up a planning session that is not running

- `<id>`
- `--yes`: confirm

### `phoenix plan list`

list planning sessions

- `--project PROJECT`: only this project

## `phoenix spec`

work with spec files

### `phoenix spec check`

check a spec file

- `<file>`
