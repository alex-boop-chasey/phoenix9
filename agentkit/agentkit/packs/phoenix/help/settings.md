# Settings

Each project has its settings file. Read a project's settings with `settings-show` (each value and where it came
from) and `settings-explain` (the plain-English plan). Change them with `settings-change` (several keys at once by
dotted name; nothing is written unless all are fine) or choose a preset with `settings-preset`. `settings-check`
lists any problems. Unknown keys are refused. Safety settings are Alex's alone: Phoenix refuses you, and Alex
changes them on the project's Settings page.

## Layer order

Lowest first; a later layer wins: library, then profile, then preset, then project, then the single build.

## Project keys

| Key | What it holds | Default | Allowed |
| --- | --- | --- | --- |
| `preset` | Which bundle of steps builds use | quick | simple, quick, full, custom |
| `based_on` | The preset a custom preset starts from | quick | simple, quick, full |
| `profile` | The kind of container the project builds in | (empty) | see Profiles |
| `merge` | Merge finished builds by themselves, or ask first | auto | auto, ask |
| `max_tries` | Tries each task gets | 3 | a whole number |
| `on_failure` | What happens when a task runs out of tries (safety setting) | pause | continue, pause, delegate |
| `budget_usd` | The cap on what one build may use (Alex's alone) | none | |
| `services` | The project's chosen services | none | |
| `safety_files` | Extra files the builder may not touch | none | |
| `home_chat_may_answer` | Kinds of question the Phoenix agent may answer | none | |
| `diff.allow_extra` | Extra files a build may change | none | |
| `diff.deny_extra` | Extra files a build may not change | none | |
| `domains.allow` | Extra web sites a build may reach | none | |
| `deploy.with` | The deployer | none | |
| `deploy.mode` | When to deploy | off | on-merge, button, off |
| `deploy.preview` | Deploy each build's branch to a temporary address first | false | true, false |

## AI step keys (under steps.name for every AI step)

| Key | What it holds | Default |
| --- | --- | --- |
| `model` | The model for this step | Phoenix's default |
| `fallback_models` | Models to use when the first is busy | none |
| `tools` | Extra tools the step may use | none |
| `tools_denied` | Tools the step may not use | none |
| `mcp_servers` | Extra tool servers | none |
| `claude_md` | Which instructions file the step reads | library (or project, or both) |
| `skills` | Extra skills | none |
| `max_turns` | The most turns one session may take | 40 |
| `timeout` | Minutes before the session is stopped | 30 |
| `advisor.on` | Let the step ask a stronger model for advice | false |
| `advisor.model` | The advisor's model | (empty) |
| `advisor.when` | When it may ask: blocked, before-done, on-demand | none |
| `advisor.instructions` | Extra words for the advisor | (empty) |

## Step keys

Every step can be turned on or off with steps.step name.on (true or false). A few have more:

| Key | What it does | Default |
| --- | --- | --- |
| `steps.planner.auto_approve` | Approve the planner's plan without asking Alex | false |
| `steps.check-writer.once` | Write checks once per task, not on every try | true |
| `steps.red-check.once` | Prove checks fail once per task, not on every try | true |
| `steps.builder.retry` | On a new try, repair the last try's work or restart from clean (repair, restart) | repair |
| `steps.verify.scope` | Which tests run after each task: task, affected or full | task |
| `steps.verify.suite_every` | Run the whole suite every this many tasks | 5 |
| `steps.reviewer.strict` | A reviewer's "no" fails the task | true |
| `steps.notify.after_stop` | Tell Alex when a build is stopped too | true |

The steps topic says what each step does.

## Presets

### simple

Just build each task and check it. No planner, check writer, verify or reviewer.
Steps: pick up, spec check, branch, service setup, red check, builder, diff rules, secret scan, acceptance,
commit, lockfile check, full suite, summary, preview, merge, deploy, notify.

### quick (the default)

Simple, plus the project's tests run after each task (the verify step).
Steps: pick up, spec check, branch, service setup, red check, builder, diff rules, secret scan, acceptance,
verify, commit, lockfile check, full suite, summary, preview, merge, deploy, notify.

### full

Everything on: a plan for the whole spec first, checks written before the code, full verification and a review by
a fresh reader.
Steps: pick up, spec check, branch, planner, service setup, check writer, red check, builder, diff rules, secret
scan, acceptance, verify, reviewer, commit, lockfile check, full suite, summary, preview, merge, deploy, notify.

### custom

Alex's own step choices on top of the preset named in `based_on`.

## Profiles

| Profile | For | Tests run with | Deploys with |
| --- | --- | --- | --- |
| desktop | Desktop apps | vitest | nothing |
| mobile | Mobile apps | vitest | Expo EAS |
| platform | Platforms | the project's check script | nothing |
| python-script | Python scripts | pytest | nothing |
| research | Research | nothing | nothing |
| web | Web apps | vitest | a VPS with Docker |

`library-profiles` lists the profiles as they are now.
