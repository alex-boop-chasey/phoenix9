# hooks

Mounted read-only at `/phoenix-hooks` in every Claude session container.
If a `settings.json` is placed here it is mounted read-only over the
session's `~/.claude/settings.json`, so the session cannot change its hooks.
Empty for now: no hooks run yet.
