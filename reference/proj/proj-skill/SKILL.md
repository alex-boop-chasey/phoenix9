---
name: proj
description: List, create, open and close Alex's project workspaces (/srv/projects/<name>). Use when Alex says "open X", "close X", "new project X", "what projects do I have", "what's running", or when a new project or Phoenix client site needs a workspace.
---

# proj

Each project is a folder `/srv/projects/<name>/` (CLAUDE.md, notes/, code/). Every project is **always
on**: its Remote Control service (`claude-rc@<name>`) starts at boot, so it shows in the Claude desktop
app and Alex starts chats in it there. Nothing sleeps. `proj close` is the only way a project goes off.

| Alex says | Run | Then tell him |
| --- | --- | --- |
| what projects do I have / what's running | `proj list` | the list in plain words (on/off, chats open, last used) |
| open X (only after a close) | `proj open X` | "X is on; it'll be in the app in a few seconds" |
| close X | `proj close X` | it won't come back at boot either; if it refuses because chats are open, say so and ask before `--force` |
| new project X | `proj new X` (`--repo owner/name` to copy a GitHub repo into code/, `--code /path` for code elsewhere) | it's on; then ask him a few questions and fill in X's CLAUDE.md (what it is, repo, code) and notes/NOW.md |

- Alex can list and create projects on the project selector too: https://files.rebirthwebdesign.com.au/proxy/8090/
  (project-selector; it runs these same commands). `proj list --json` is the page's data feed.
- Names: lowercase letters, digits, dashes.
- Every new project of any kind gets a workspace first, whether it will be built by a chat, grunt or Phoenix.
- Each project folder has .vscode/tasks.json: opening /srv/projects/<name> in VS Code runs `proj open <name>`
  (a no-op unless the project was closed). Chats are not started from VS Code.
- Every 15 minutes `proj sweep` (proj-sweep.timer) backs the notes up to alex-boop-chasey/projects.
- Closing the project a chat is running in ends that chat; never `--force` without Alex's OK.
- Code for a project goes in its `code/` folder (outside /root, so grunt can work on it). Phoenix's code
  is the exception: /docker/phoenix-v8.
- `proj` itself: /srv/projects/tools/proj (linked from /usr/local/bin/proj); service recipe
  /etc/systemd/system/claude-rc@.service; design notes /srv/projects/home/notes/specs/.
