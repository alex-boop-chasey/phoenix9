<!-- phoenix 9.1.0 inputs 94b61d67e53ba7a5 -->
# Settings (phoenix.toml)

Change with `phoenix settings`. Unknown keys are errors.

## Layer order

Lowest first; a later layer wins: library < profile < preset < project < run.

## Project keys

| Key | Type | Default | Allowed |
| --- | --- | --- | --- |
| `preset` | str | 'quick' | simple, quick, full, custom |
| `based_on` | str | 'quick' | simple, quick, full |
| `profile` | str | '' |  |
| `merge` | str | 'auto' | auto, ask |
| `max_tries` | int | 3 |  |
| `on_failure` | str | 'pause' | continue, pause, delegate |
| `budget_usd` | int or float | (none) |  |
| `services` | list of str | [] |  |
| `safety_files` | list of str | [] |  |
| `home_chat_may_answer` | list of str | [] |  |
| `diff.allow_extra` | list of str | [] |  |
| `diff.deny_extra` | list of str | [] |  |
| `domains.allow` | list of str | [] |  |
| `deploy.with` | str | 'none' |  |
| `deploy.mode` | str | 'off' | on-merge, button, off |
| `deploy.preview` | bool | false |  |

## AI keys (under `steps.<name>` for every ai step)

| Key | Type | Default | Allowed |
| --- | --- | --- | --- |
| `model` | str | '' |  |
| `fallback_models` | list of str | [] |  |
| `tools` | list of str | [] |  |
| `tools_denied` | list of str | [] |  |
| `mcp_servers` | list of str | [] |  |
| `claude_md` | str | 'library' | library, project, both |
| `skills` | list of str | [] |  |
| `max_turns` | int | 40 |  |
| `timeout` | int | 30 |  |
| `advisor.on` | bool | false |  |
| `advisor.model` | str | '' |  |
| `advisor.when` | list of str | [] | blocked, before-done, on-demand |
| `advisor.instructions` | str | '' |  |

## Step keys (`steps.<name>.<key>`)

| Key | Type | Default | Allowed |
| --- | --- | --- | --- |
| `steps.pick-up.on` | bool | true |  |
| `steps.spec-check.on` | bool | true |  |
| `steps.branch.on` | bool | true |  |
| `steps.planner.on` | bool | false |  |
| `steps.service-setup.on` | bool | true |  |
| `steps.check-writer.on` | bool | false |  |
| `steps.check-writer.once` | bool | true |  |
| `steps.red-check.on` | bool | true |  |
| `steps.red-check.once` | bool | true |  |
| `steps.builder.on` | bool | true |  |
| `steps.builder.retry` | str | 'repair' | repair, restart |
| `steps.diff-rules.on` | bool | true |  |
| `steps.secret-scan.on` | bool | true |  |
| `steps.acceptance.on` | bool | true |  |
| `steps.verify.on` | bool | true |  |
| `steps.verify.scope` | str | 'task' | task, affected, full |
| `steps.verify.suite_every` | int | 5 |  |
| `steps.reviewer.on` | bool | false |  |
| `steps.reviewer.strict` | bool | true |  |
| `steps.commit.on` | bool | true |  |
| `steps.lockfile.on` | bool | true |  |
| `steps.full-suite.on` | bool | true |  |
| `steps.summary.on` | bool | true |  |
| `steps.preview.on` | bool | true |  |
| `steps.merge.on` | bool | true |  |
| `steps.deploy.on` | bool | true |  |
| `steps.notify.on` | bool | true |  |
| `steps.notify.after_stop` | bool | true |  |

## Presets

### simple

Just build each task and check it. No planner, check writer, verify or reviewer.

Steps: pick-up, spec-check, branch, service-setup, red-check, builder, diff-rules, secret-scan, acceptance, commit, lockfile, full-suite, summary, preview, merge, deploy, notify

### quick

Simple, plus the project's tests run after each task.

Steps: pick-up, spec-check, branch, service-setup, red-check, builder, diff-rules, secret-scan, acceptance, verify, commit, lockfile, full-suite, summary, preview, merge, deploy, notify

### full

Everything on: plan, checks first, full verification and a review.

Steps: pick-up, spec-check, branch, planner, service-setup, check-writer, red-check, builder, diff-rules, secret-scan, acceptance, verify, reviewer, commit, lockfile, full-suite, summary, preview, merge, deploy, notify

- `custom`: your own step choices on top of `based_on`.

## Profiles

- `desktop`: Desktop app; image `phoenix9-step-desktop:1`; test `pnpm test`; deployer `none`
- `mobile`: Mobile app; image `phoenix9-step-mobile:1`; test `pnpm test`; deployer `expo-eas`
- `platform`: Platform; image `phoenix9-step-platform:1`; test `./check.sh`; deployer `none`
- `python-script`: Python script; image `phoenix9-step-python:1`; test `python3 -m pytest -q`; deployer `none`
- `research`: Research; image `phoenix9-step-research:1`; test `true`; deployer `none`
- `web`: Web app; image `phoenix9-step-web:1`; test `pnpm test`; deployer `vps-docker`
