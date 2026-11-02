# Phase 4.5: project list fixes (Alex, 2026-11-01)

Runs as one grunt job straight after phase 4's grunt job, stacked on its branch. Step sheets are
written from the real phase 4 code when phase 4 finishes (same alignment method as before).

## 1. Chat and VS Code links that always work
Found: the preview's links are demo-only (fake ids), so failures there were expected. On the real
server all 7 claude-rc@ chats currently log an environment link, but Phoenix finds it by reading only
the last few hundred journal lines, so a busy or restarted chat can push it out and the link goes
missing or stale.
- Record the environment id in .phoenix/project.json whenever it is seen; refresh it on every chat
  service (re)start (read the journal since the unit's last start, not a fixed line count).
- If no id is known: show "Start chat" (switches the chat service on) instead of a dead link.
- VS Code link: verify the folder exists; use the /srv/projects/<name> path.
- `phoenix doctor` checks every project's chat and VS Code links and reports any that are missing.
- Tests with fake journal output (rotated logs, restart, no link, chat off).

## 2. Remove from Phoenix (keeps everything)
- A "Remove" action on each project (in the card's menu, with a confirm step) that removes the project
  from Phoenix's list WITHOUT deleting anything.
- DECIDED (Alex): Remove takes the project's Remote Control chat away from the folder so the project
  automatically disappears from the Claude app: stop and disable claude-rc@<name>, and undo the
  folder's Remote Control set-up (whatever `proj new/open` did for it, e.g. the trust entry), so it is
  no longer offered under "+" in the Claude desktop app. The folder, notes, code, repo and keys stay
  untouched. Recorded in Phoenix's global config (a removed-projects list) plus a changelog line.
- To verify on the real server during the phase: after Remove, the project's environment no longer
  shows in the Claude app (if claude.ai keeps listing an offline environment, find and document the
  supported way to remove it; never touch other projects' chats).
- Never allowed on the phoenix9 project itself or the home project.
- `phoenix project remove <name> --yes` (CLI and API).

## 3. "Add project" button with a chevron
- Replaces "Create new project". Clicking opens a dropdown with two options, shown as mini styled cards:
  - **Create new**: today's New project form. Creating a project ALWAYS sets up and starts its Remote
    Control chat (claude-rc@<name>: trust the folder, enable at boot, start), so it appears under "+"
    in the Claude desktop app straight away; the page shows when the chat is live.
  - **Import**: bring in a project that already exists: one removed from Phoenix earlier, or a
    workspace made before Phoenix or outside it (folders in /srv/projects not yet listed, or a path).
    Import lists candidates with name, path and repo; importing adds it back, records it, and ALWAYS
    sets its Remote Control chat back up in the folder (trust, enable, start) so it reappears in the
    Claude app. A folder without CLAUDE.md/notes gets the
    standard workspace files added (nothing overwritten).
- `phoenix project import <name|path>` (CLI and API).

## Notes
- The phase 5 redesign restyles these later (Ember Forge cards with repo/VS Code/chat buttons; the Add
  project dropdown items as mini cards); phase 4.5 builds the behaviour in the current UI.
- Tests: pytest for ops/CLI/API with fakes; Vitest for the dropdown, remove confirm and import list;
  Playwright pass on the demo server.
