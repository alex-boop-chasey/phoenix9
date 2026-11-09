<!-- phoenix 9.1.0 inputs 57363ddab20a599e -->
# Dashboard pages

Link with `phoenix ui open` style routes; params go in the hash in this order.

## `projects`

The home page: every project as a row with its status, owner and what needs Alex.

- params: q, status, owner, sort, attention

## `new`

The new-project wizard: name, owner, template and first spec.

- params: (none)

## `p/<name>/overview`

One project: its state, open gates (Needs you) and recent builds.

- params: gate

## `p/<name>/build`

One project's builds: start a build, follow a run's steps and tasks; `wizard` opens a slide of the build wizard (1 to 7).

- params: run, wizard

## `p/<name>/logs`

One project's logs and run documents; `run`, `step`, `task`, `kind` and `log` pick what to show.

- params: run, step, task, kind, log

## `p/<name>/settings`

One project's settings (sections: project, build); `key` jumps to one setting.

- params: section, key

## `settings`

Phoenix's own settings (sections: services, models, updates, addresses).

- params: section
