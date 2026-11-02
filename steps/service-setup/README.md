# Service setup

Runs once at the start of a run, after Branch. For each service in the project's `services` list it
checks the project keys have values, makes sure the service's hosts are in the project's
`[domains] allow`, and (the first time only) runs the service's `recipe.py`. It then writes
`services.md` in the run folder (service titles, env var names, install notes; never values) for the Builder.
Missing keys open a "Paste keys" gate; answer `done` once pasted, or `skip` to go on without them.
