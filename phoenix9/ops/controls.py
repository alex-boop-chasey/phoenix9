"""The controls registry: every dashboard control once (its route, risk and whether the agent may use it)."""
from dataclasses import dataclass, field

NAME = r"(?P<name>[^/]+)"  # the same project-name pattern as phoenix9/api/server.py
RUN = r"(?P<project>[^/]+)/(?P<run_id>[^/]+)"
GATE = r"(?P<gate_id>[^/]+)"
SUGGEST = r"(?P<key>[A-Za-z0-9._:+%-]+)"

RISKS = ("read", "change", "destructive", "alex-only")
AGENTS = ("tool", "alex-only", "key-card", "secret", "later")
TYPES = ("string", "integer", "boolean", "choice", "list", "object")
WHERES = ("path", "query", "body")


@dataclass(frozen=True)
class Input:
    """One thing a control needs: its name, type, where it goes in the request and what it means."""
    name: str
    type: str = "string"
    required: bool = False
    description: str = ""
    choices: tuple = ()
    where: str = "body"
    into: tuple = ()  # body path when it differs from the name, e.g. ("set", "steps.notify.on")


@dataclass(frozen=True)
class Control:
    """One dashboard control: what it calls, how it is reached, how risky it is and what the agent may do."""
    name: str
    ops: str  # "module.function" in phoenix9/ops ("" when the API layer answers by itself)
    method: str
    route: str  # the same pattern as in phoenix9/api/server.py ROUTES
    risk: str
    agent: str
    why: str = ""  # required unless agent is "tool"
    text: str = ""  # the description for the model; empty = the first docstring line of the ops function
    inputs: tuple = ()
    fixed: dict = field(default_factory=dict)  # body values always sent (e.g. a gate action)
    fixed_query: dict = field(default_factory=dict)  # query values always sent
    card: str = ""  # the result card name
    confirm_with: str = ""  # destructive: the input whose value Alex must type


def _in(name, type="string", required=False, description="", choices=(), where="body", into=()) -> Input:
    """Make one input."""
    return Input(name, type, required, description, tuple(choices), where, tuple(into))


P_NAME = _in("name", required=True, description="The project's name.", where="path")
P_PROJECT = _in("project", required=True, description="The project's name.", where="path")
P_RUN = _in("run_id", required=True, description="The run's id.", where="path")
P_GATE = _in("gate_id", required=True, description="The question's id (from the list of open questions).", where="path")
Q_PROJECT = _in("project", description="Only this project's.", where="query")
GATE_NOTE = _in("note", description="Your words to the build.")
LATER = "Planned for a later agent build; for now Alex uses the dashboard."
DASH = "Not part of the agent's job in this build; Alex uses the dashboard."


def _get(name, ops, route, agent, why="", **kw) -> Control:
    """A read control."""
    return Control(name, ops, "GET", route, "read", agent, why, **kw)


def _post(name, ops, route, risk, agent, why="", **kw) -> Control:
    """A control that changes something."""
    return Control(name, ops, "POST", route, risk, agent, why, **kw)


CONTROLS = (
    # ---- projects ----
    _get("projects-list", "projects.rows", "/api/projects", "tool", card="project_cards",
         text="List projects, with search and filter options.",
         inputs=(_in("q", description="Search words.", where="query"),
                 _in("status", description="Only projects in this state.", where="query"),
                 _in("owner", description="Only projects with this owner.", where="query"),
                 _in("sort", description="Sort order.", where="query"),
                 _in("attention", "boolean", description="Only projects that need Alex.", where="query"))),
    _get("project-show", "projects.show", rf"/api/projects/{NAME}", "tool", inputs=(P_NAME,), card="project_cards"),
    _get("project-check-name", "projects.check_name", "/api/projects/check-name", "tool",
         inputs=(_in("name", required=True, description="The project name to check.", where="query"),)),
    _get("project-changelog", "projects.changelog", rf"/api/projects/{NAME}/changelog", "later", LATER),
    _get("project-specs", "projects.specs", rf"/api/projects/{NAME}/specs", "tool", inputs=(P_NAME,)),
    Control("project-delete-plan", "projects.delete_plan", "GET", rf"/api/projects/{NAME}/delete-plan", "alex-only",
            "alex-only", "Part of deleting a project, which only Alex does."),
    _post("project-create", "", "/api/projects", "change", "tool", card="project_cards",
          text="Create a new project in the background; the result carries the job id to follow.",
          inputs=(_in("name", required=True, description="The new project's name."),
                  _in("description", description="One line about the project."),
                  _in("profile", description="The project type (a profile name from the library)."),
                  _in("source", "object", description='Where it starts: {"kind": "empty"} or '
                      '{"kind": "template", "template": "<template name>"}.'),
                  _in("new_repo", "object", description='A new GitHub repo: {"on": true, "owner": "<owner>"} '
                      'or {"on": false}.'),
                  _in("services", "list", description="The names of the services the project uses."))),
    _post("project-import", "projects.import_", "/api/import", "change", "later", LATER),
    _get("import-candidates", "projects.import_candidates", "/api/import/candidates", "later", LATER),
    _get("folders-list", "projects.list_folders", "/api/folders", "later", LATER),
    _post("project-edit", "projects.edit", rf"/api/projects/{NAME}/edit", "change", "later",
          "Changing a project's description, repo or profile is a later agent build."),
    _post("project-services-set", "projects.set_services", rf"/api/projects/{NAME}/edit", "change", "tool",
          inputs=(P_NAME, _in("services", "list", True, "The names of the services the project uses.")),
          card="project_cards"),
    _post("project-remove", "projects.remove", rf"/api/projects/{NAME}/remove", "destructive", "later", LATER),
    _post("project-delete", "projects.delete", rf"/api/projects/{NAME}/delete", "alex-only", "alex-only",
          "Deleting a project is Alex's alone; point Alex to the Delete button on the dashboard.",
          inputs=(P_NAME,)),
    _post("project-delete-repo", "projects.delete_repo", rf"/api/projects/{NAME}/delete-repo", "alex-only",
          "alex-only", "Deleting a repo is Alex's alone; point Alex to the Delete repo button on the dashboard.",
          inputs=(P_NAME,)),
    # ---- project settings ----
    _get("settings-show", "settings.show", rf"/api/projects/{NAME}/settings", "tool", inputs=(P_NAME,),
         card="settings_card"),
    _get("settings-explain", "settings.explain", rf"/api/projects/{NAME}/explain", "tool", inputs=(P_NAME,),
         card="settings_card"),
    _post("settings-check", "settings.check", rf"/api/projects/{NAME}/settings/check", "change", "tool",
          inputs=(P_NAME,), card="settings_card"),
    _post("settings-change", "settings.set_many", rf"/api/projects/{NAME}/settings", "change", "tool",
          inputs=(P_NAME, _in("set", "object", True, "The settings to change: {setting name: new value}.")),
          card="settings_card"),
    _post("settings-preset", "settings.preset", rf"/api/projects/{NAME}/settings/preset", "change", "tool",
          inputs=(P_NAME, _in("preset", required=True, description="The preset's name.")), card="settings_card"),
    _post("settings-defaults", "settings.save_defaults", rf"/api/projects/{NAME}/defaults", "change", "later", LATER),
    _post("notifications-set", "settings.set_many", rf"/api/projects/{NAME}/settings", "change", "tool",
          text="Turn a project's build notifications on or off.",
          inputs=(P_NAME, _in("on", "boolean", True, "True to turn notifications on, false to turn them off.",
                              into=("set", "steps.notify.on"))),
          card="settings_card"),
    # ---- keys ----
    _get("keys-list", "keys.rows", rf"/api/projects/{NAME}/keys", "tool", inputs=(P_NAME,), card="keys_card",
         text="List a project's key names and whether each is set; values are never shown."),
    _post("keys-save", "keys.save", rf"/api/projects/{NAME}/keys/save", "change", "key-card",
          "Key values are typed into the masked key card, which posts them straight to Phoenix.",
          inputs=(P_NAME,)),
    _post("keys-reveal", "keys.reveal", rf"/api/projects/{NAME}/keys/reveal", "change", "secret",
          "Revealing a key would put its value through the model."),
    _post("keys-remove", "keys.remove", rf"/api/projects/{NAME}/keys/remove", "destructive", "later", LATER),
    _get("keys-audit", "keys.audit", "/api/keys/audit", "later", LATER),
    # ---- services ----
    _get("services-list", "services.list_", "/api/services", "tool", card="services_card",
         text="List every service and whether it is connected."),
    _get("services-global", "services.list_global", "/api/global/services", "later", LATER),
    _post("service-connect", "services.connect", rf"/api/services/{NAME}/connect", "change", "secret",
          "Connecting a service sends key values, which must never go through the model."),
    _post("service-test", "services.test", rf"/api/services/{NAME}/test", "change", "secret",
          "Testing a service with values would put key values through the model."),
    _post("service-disconnect", "services.disconnect", rf"/api/services/{NAME}/disconnect", "destructive", "later",
          LATER),
    # ---- builds and runs ----
    _post("build-plan", "runs.plan", rf"/api/projects/{NAME}/plan", "read", "tool",
          inputs=(P_NAME, _in("overrides", "object", description="Optional settings to try for this build."))),
    _post("build-start", "runs.start_from_notes", rf"/api/projects/{NAME}/runs", "change", "tool",
          inputs=(P_NAME, _in("spec", description="The spec to build (the newest one if left out)."),
                  _in("brief", description="A short brief to build from instead of a spec."),
                  _in("overrides", "object", description="Settings to use for this build only.")),
          card="run_card"),
    _post("hotfix-start", "runs.start_hotfix", rf"/api/projects/{NAME}/hotfix", "change", "tool",
          inputs=(P_NAME, _in("brief", description="A small description of the change to make.", required=True)),
          card="run_card",
          text="Start a short build on its own branch from a small description of the change. "
               "One at a time per project."),
    _post("build-pause", "runs.pause", r"/api/runs/(?P<run_id>[^/]+)/pause", "change", "tool",
          inputs=(P_RUN,), fixed={"now": True}, card="run_card"),
    _post("build-resume", "runs.resume", r"/api/runs/(?P<run_id>[^/]+)/resume", "change", "tool",
          inputs=(P_RUN,), card="run_card"),
    _post("build-stop", "runs.stop", rf"/api/runs/{RUN}/stop", "destructive", "tool",
          inputs=(P_PROJECT, P_RUN), fixed={"confirm": True}, card="run_card", confirm_with="run_id"),
    _post("build-note", "runs.note", r"/api/runs/(?P<run_id>[^/]+)/note", "change", "later", LATER),
    _post("build-discard", "runs.discard", rf"/api/runs/{RUN}/discard", "destructive", "later", LATER),
    _get("builds-list", "runs.builds", rf"/api/projects/{NAME}/runs", "tool", card="RunCards",
         text="List a project's recent builds, newest first, each with status, finish time and the failed task's one-line reason.",
         inputs=(P_NAME, _in("limit", "integer", description="How many builds at most (10 if left out).", where="query"))),
    _get("run-show", "runs.detail", rf"/api/runs/{RUN}", "tool", inputs=(P_PROJECT, P_RUN), card="run_card"),
    _get("run-events", "runs.events", rf"/api/runs/{RUN}/events", "tool", card="events_card",
         text="Read one run's events, oldest first.",
         inputs=(P_PROJECT, P_RUN, _in("after", "integer", description="Only events after this number.", where="query"),
                 _in("limit", "integer", description="How many events at most (50 if left out).", where="query"))),
    _get("bell", "bell.show", "/api/bell", "tool", card="bell_card",
         text="Read the bell: everything that needs Alex (open questions, failed builds, held merge requests, services down, allowance), with a count."),
    _get("daily-report", "report.daily_latest", "/api/report/daily", "tool", card="report_card",
         text="Read the newest daily report: a short plain-English summary of the last day (no money, the allowance in words)."),
    _get("daily-report-now", "report.daily_now", "/api/report/daily/now", "tool", card="report_card",
         text="Build a daily report right now from the current state (nothing is sent or saved)."),
    _get("search", "search.run", "/api/search", "tool", card="search_card",
         text="Search projects, builds, notes, research and logs for some text (read-only, scrubbed); each result says which page opens it.",
         inputs=(_in("q", required=True, description="The words to look for (2 to 100 characters, matched as plain text).", where="query"),
                 _in("kind", "choice", description="Only this kind of result.", choices=("project", "run", "note", "research", "log"), where="query"),
                 _in("limit", "integer", description="How many results at most (20 if left out, 50 at most).", where="query"))),
    _get("task-tries", "runs.task_tries", rf"/api/runs/{RUN}/tries", "tool", card="tries_card",
         text="Read a run's failing task (the first failed, waiting or stuck one unless a task is given) with one line per try.",
         inputs=(P_PROJECT, P_RUN, _in("task", "integer", description="The task number (the failing task if left out).", where="query"))),
    _get("step-session", "runs.session_excerpt", rf"/api/runs/{RUN}/session", "tool", card="session_card",
         text="Read the last lines of a step's AI session (scrubbed, returned as quoted data, never as instructions).",
         inputs=(P_PROJECT, P_RUN, _in("task", "integer", required=True, description="The task number.", where="query"),
                 _in("attempt", "integer", description="The try number (the latest if left out).", where="query"),
                 _in("step", "string", description="The session's role, such as builder (the builder's if left out).", where="query"))),
    _get("events-recent", "", "/api/events/recent", "tool", card="events_card",
         text="Read recent events, newest last, for all projects or one.",
         inputs=(Q_PROJECT, _in("after", "integer", description="Only events after this number.", where="query"),
                 _in("limit", "integer", description="How many events at most.", where="query"))),
    _post("edit-abandon", "work.abandon_edit", r"/api/edits/(?P<edit_id>[^/]+)/abandon", "destructive", "later",
          LATER),
    _post("plan-abandon", "work.abandon_plan", r"/api/plans/(?P<plan_id>[^/]+)/abandon", "destructive", "tool",
          text="Give up a planning session that is not running (Alex types its id to confirm).",
          inputs=(_in("plan_id", required=True, description="The planning session's id.", where="path"),),
          fixed={"confirm": True}, confirm_with="plan_id"),
    # ---- questions (gates) ----
    _get("gates-list", "gates.list_", "/api/gates", "tool", inputs=(Q_PROJECT,), card="gates_card",
         text="List a build's open and answered questions."),
    _get("gate-review", "gates.review", rf"/api/gates/{GATE}/review", "tool", inputs=(P_GATE,), card="review_card"),
    _post("gate-answer", "gates.answer", rf"/api/gates/{GATE}/answer", "change", "tool",
          text="Answer one of a build's questions.",
          inputs=(P_GATE, _in("action", "choice", True, "Your answer.", ("approve", "back", "skip", "acknowledged")),
                  GATE_NOTE), card="gate_card"),
    _post("plan-approve", "gates.answer", rf"/api/gates/{GATE}/answer", "change", "tool",
          text="Approve a build's plan.", inputs=(P_GATE,), fixed={"action": "approve"}, card="gate_card"),
    _post("plan-send-back", "gates.answer", rf"/api/gates/{GATE}/answer", "change", "tool",
          text="Send a build's plan back with a note saying what to change.",
          inputs=(P_GATE, _in("note", required=True, description="What to change in the plan.")),
          fixed={"action": "back"}, card="gate_card"),
    _post("merge-answer", "gates.answer", rf"/api/gates/{GATE}/answer", "change", "tool",
          text="Answer a build's merge question: approve the merge, send it back or skip it.",
          inputs=(P_GATE, _in("action", "choice", True, "Your answer.", ("approve", "back", "skip")), GATE_NOTE),
          card="gate_card"),
    # ---- repair ----
    _get("run-diagnose", "repair.diagnose", r"/api/repair/(?P<run_id>[^/]+)/diagnose", "tool", card="diagnose_card",
         text="Say why a run stopped or failed: the cause in plain words, what was tried and which repairs fit.",
         inputs=(_in("run_id", required=True, description="The run's id.", where="path"),
                 _in("project", required=True, description="The project's name.", where="query"))),
    _get("repair-report", "repair.report", r"/api/repair/(?P<run_id>[^/]+)/report", "later",
         "Repair of failed builds is build 3."),
    _post("repair-apply", "repair.apply_text", r"/api/repair/(?P<run_id>[^/]+)/apply", "change", "later",
          "Free-text repair notes stay out of the agent's hands; it repairs only through the controls below."),
    _post("repair-rerun-step", "repair.rerun_step", rf"/api/runs/{RUN}/repair/rerun", "change", "tool",
          text="Re-run one task of a stopped or failed run, or one of its finish steps (give a task number or a finish step name).",
          inputs=(P_PROJECT, P_RUN, _in("task", "integer", description="The task number to run again."),
                  _in("finish_step", description="The finish step's name to run again (instead of a task).")),
          card="repair_card"),
    _post("repair-resume-from", "repair.resume_from", rf"/api/runs/{RUN}/repair/resume", "change", "tool",
          text="Resume a stopped or failed run from a task: that task runs again, then the build carries on.",
          inputs=(P_PROJECT, P_RUN, _in("task", "integer", required=True, description="The task number to resume from.")),
          card="repair_card"),
    _post("repair-skip-task", "repair.skip_task", rf"/api/runs/{RUN}/repair/skip", "change", "tool",
          text="Skip a task of a run, with the reason shown on the approval card.",
          inputs=(P_PROJECT, P_RUN, _in("task", "integer", required=True, description="The task number to skip."),
                  _in("why", required=True, description="Why the task may be skipped, in one plain line.")),
          card="repair_card"),
    _post("repair-rewrite-checks", "repair.rewrite_checks", rf"/api/runs/{RUN}/repair/rewrite-checks", "change", "tool",
          text="Have a task's checks rewritten, with the reason shown on the approval card (locked checks are never unlocked).",
          inputs=(P_PROJECT, P_RUN, _in("task", "integer", required=True, description="The task number whose checks are rewritten."),
                  _in("why", required=True, description="Why the checks are wrong, in one plain line.")),
          card="repair_card"),
    _post("repair-raise-max-tries", "repair.raise_max_tries", rf"/api/runs/{RUN}/repair/max-tries", "change", "tool",
          text="Raise how many tries each task of this run gets (never lower, never above the fixed limit).",
          inputs=(P_PROJECT, P_RUN, _in("tries", "integer", required=True, description="The new number of tries per task.")),
          card="repair_card"),
    _post("repair-restart-preset", "repair.restart_on_preset", rf"/api/runs/{RUN}/repair/restart", "change", "tool",
          text="Start the build again from the same spec on another preset (the old run stays as it is).",
          inputs=(P_PROJECT, P_RUN, _in("preset", required=True, description="The preset to restart on.")),
          card="repair_card"),
    # ---- updates ----
    _get("update-check", "update.status", "/api/update", "tool", card="update_card",
         text="Check whether a newer Phoenix is available.", fixed_query={"refresh": "1"}),
    _get("update-log", "update.log", "/api/update/log", "later", LATER),
    _get("update-history", "update.history", "/api/update/history", "later", LATER),
    _post("update-install", "update.install", "/api/update/install", "change", "tool",
          text="Ask Phoenix to install a newer version (the newest when no version is given).",
          inputs=(_in("tag", description="The version to install."),), fixed={"yes": True}, card="update_card"),
    _post("update-rollback", "update.rollback", "/api/update/rollback", "destructive", "later", LATER),
    # ---- global settings ----
    _get("global-show", "app.global_view", "/api/global", "tool", card="global_card"),
    _post("global-models", "app.set_default_models", "/api/global/models", "change", "tool",
          inputs=(_in("steps", "object", True, "{step: {model, fallback_models}} for each step to change."),),
          card="global_card"),
    _post("global-addresses", "app.set_addresses", "/api/global/addresses", "destructive", "tool",
          text="Change the dashboard addresses; changing the allowed origins restarts the Phoenix API.",
          inputs=(_in("dashboard_url", description="The dashboard's address."),
                  _in("allowed_origins", description="The addresses allowed to use the API, separated by commas."),
                  _in("vscode_url", description="The address of the code editor.")),
          card="global_card", confirm_with="allowed_origins"),
    # ---- doctor ----
    _get("doctor-run", "doctor.run", "/api/doctor", "tool", card="doctor_card",
         inputs=(_in("mode", "choice", description="How thorough to be.", choices=("quick", "full"), where="query"),)),
    # ---- other dashboard pages ----
    _get("info", "app.info", "/api/info", "later", DASH),
    _get("routes", "agentaccess.pages", "/api/routes", "tool",
         text="List the dashboard pages the agent can point Alex to.", card="routes_card"),
    _get("health", "", "/api/health", "later", "Answers the service check; not a control."),
    _get("job-status", "", "/api/jobs/(?P<job_id>[0-9a-f]+)", "tool",
         text="Progress of a background job (for example a project being created).",
         inputs=(_in("job_id", required=True, description="The job's id.", where="path"),)),
    _get("deploys-list", "deploy.status", rf"/api/projects/{NAME}/deploys", "later", LATER),
    _post("deploy-start", "", rf"/api/projects/{NAME}/deploy", "destructive", "later", LATER),
    _post("images-build", "images.choose", "/api/images/build", "change", "later", LATER),
    _post("service-restart", "service.restart_api_soon", rf"/api/service/{NAME}/restart", "destructive", "later",
          LATER),
    _get("chat-show", "chat.chat_state", rf"/api/chat/{NAME}", "tool", inputs=(P_NAME,),
         text="Say whether a project's chat is on, awake or asleep, and its links."),
    _post("chat-open", "chat.open_chat", rf"/api/chat/{NAME}/open", "change", "tool", inputs=(P_NAME,),
          text="Open a project's chat (starting it if needed)."),
    _post("chat-sleep", "chat.sleep_chat", rf"/api/chat/{NAME}/sleep", "change", "tool", inputs=(P_NAME,),
          text="Put a project's chat to sleep."),
    _post("chat-off", "chat.off_chat", rf"/api/chat/{NAME}/off", "destructive", "tool", inputs=(P_NAME,),
          text="Turn a project's chat off (Alex types the project name to confirm).",
          fixed={"confirm": True}, confirm_with="name"),
    _get("cards-build", "cards.build", "/api/cards", "later", "The dashboard's card builder; not a control."),
    _get("docs-list", "docs.list", "/api/docs/list", "later", LATER),
    _get("docs-show", "docs.show", "/api/docs/show", "later", LATER),
    _get("docs-download", "docs.download", "/api/docs/download", "later", LATER),
    _get("logs-list", "logs.list_", "/api/logs", "later", LATER),
    _get("logs-read", "logs.read", "/api/logs/read", "later", LATER),
    _get("library-steps", "library.steps", "/api/library/steps", "later", LATER),
    _get("library-profiles", "library.profiles", "/api/library/profiles", "tool"),
    _get("library-presets", "library.presets", "/api/library/presets", "later", LATER),
    _get("library-templates", "projects.templates_menu", "/api/library/templates", "tool"),
    _get("library-services", "library.services", "/api/library/services", "tool"),
    _get("library-tools", "library.tools", "/api/library/tools", "later", LATER),
    _get("github-repos", "github.repos", "/api/github/repos", "later", LATER),
    _post("blocks-check", "blocks.check", "/api/blocks/check", "read", "later", "A dashboard editor helper; not a control."),
    _post("ui-go", "ui.go", "/api/ui/go", "read", "later", "The agent's go_to tool has its own route (build 1)."),
    # ---- the old agent's own controls ----
    _get("agent-status", "agent.status", "/api/agent", "later", "The old Phoenix agent's panel; not for the new agent."),
    _get("agent-messages", "agent.messages", "/api/agent/messages", "later", "The old Phoenix agent's panel."),
    _get("agent-sessions", "agent.sessions", "/api/agent/sessions", "later", "The old Phoenix agent's panel."),
    _post("agent-send", "agent.send", "/api/agent/send", "change", "later", "The old Phoenix agent's panel."),
    _post("agent-restart", "agent.restart", "/api/agent/restart", "destructive", "later", "The old agent's panel."),
    _post("agent-stop", "agent.stop", "/api/agent/stop", "destructive", "later", "The old agent's panel."),
    _post("agent-new", "agent.new_conversation", "/api/agent/new", "destructive", "later", "The old agent's panel."),
    # ---- suggestions, report ----
    _get("suggest-list", "suggest.list_", "/api/suggest", "later", "Suggestions are build 5."),
    _post("suggest-snooze", "suggest.mark", rf"/api/suggest/{SUGGEST}/snooze", "change", "later", "Suggestions are build 5."),
    _post("suggest-dismiss", "suggest.mark", rf"/api/suggest/{SUGGEST}/dismiss", "change", "later", "Suggestions are build 5."),
    _post("suggest-shown", "suggest.mark", rf"/api/suggest/{SUGGEST}/shown", "change", "later", "Suggestions are build 5."),
    _get("report-status", "report.saved", "/api/report/status", "later", "The daily report is build 5."),
)

HELPERS = {
    # repair ops the agent controls will wrap (registered as controls in a later task)
    "repair.rerun_step": "Internal: re-run a task or finish step through a repair note.",
    "repair.resume_from": "Internal: retry a task and resume the run through a repair note.",
    "repair.skip_task": "Internal: skip a task, with a reason, through a repair note.",
    "repair.rewrite_checks": "Internal: rewrite a task's checks, with a reason, through a repair note.",
    "repair.raise_max_tries": "Internal: raise the run's max tries through a repair note.",
    "repair.restart_on_preset": "Internal: restart a stopped or failed build on another preset.",
    # the agent's own link into Phoenix
    "agentaccess.is_agent": "Internal: tells whether a connection is the agent's.",
    "agentnext.call": "Internal: the pass-through to the agent service (not a control).",
    "agentnext.tell_no_key": "Internal: the pass-through's no-key message.",
    # app
    "app.release_tag": "Internal: the installed release tag.",
    "app.version_label": "Internal: the version text for the footer.",
    "app.dashboard_url": "Internal: the dashboard address other code links to.",
    "app.addresses_view": "Internal: part of the global settings view.",
    "app.migrate_addresses_at_start": "Runner-only: runs once when the API starts.",
    "app.migrate_addresses": "Internal: one-time address migration.",
    "app.default_models": "Internal: part of the global settings view.",
    "app.origins_digest": "Internal: the health check's fingerprint of the allowed origins.",
    "app.allowed_peer_uids": "Internal: the API's guard.",
    "app.write_peer_uid": "Internal: the API's guard.",
    "app.access_lock_problem": "Internal: a doctor check.",
    # chat
    "chat.catch_up_todo": "Internal: part of a project chat.",
    "chat.catch_up": "Internal: part of a project chat.",
    # common
    "common.project_lock": "Internal helper.",
    "common.make_adapters": "Internal helper.",
    "common.library": "Internal helper.",
    "common.project_dir": "Internal helper.",
    "common.record_command": "Internal helper.",
    # cards
    "cards.summary": "Internal: card text helper.",
    "cards.block": "Internal: card block helper.",
    # deploy
    "deploy.deployers": "Internal: the deploy tools list.",
    "deploy.now": "CLI-only: runs a deploy from the command line.",
    # github
    "github.status": "CLI-only: GitHub connection check.",
    "github.prs": "CLI-only: lists pull requests.",
    # keys
    "keys.list_": "CLI-only: `phoenix project keys` (the dashboard uses keys.rows).",
    "keys.set_": "CLI-only: `phoenix project key set` (the dashboard uses keys.save).",
    "keys.load_secrets": "Runner-only: loads key values for a step's key proxy.",
    # logs
    "logs.render_session": "Internal: log page helper.",
    "logs.render_gate": "Internal: log page helper.",
    "logs.render_commands": "Internal: log page helper.",
    # images
    "images.build": "CLI-only: builds step images (the dashboard goes through images.choose).",
    # projects
    "projects.agent_name": "Internal: the agent's folder name.",
    "projects.list_": "CLI-only: `phoenix project list`.",
    "projects.new": "CLI-only: `phoenix project new` (the dashboard creates through the API layer).",
    "projects.check_files": "Internal: project file check.",
    "projects.agent_work": "Internal: the agent's own work listing.",
    "projects.chat_or_none": "Internal: project row helper.",
    "projects.state_of": "Internal: project row helper.",
    "projects.created_at": "Internal: project row helper.",
    "projects.modified_at": "Internal: project row helper.",
    "projects.query": "Internal: the filtered form of the project list (projects.rows is the control).",
    "projects.row": "Internal: one project row (part of project show).",
    # repair
    "repair.undo": "CLI-only: undo a repair.",
    "repair.check": "Internal: part of the repair report.",
    "repair.resume": "CLI-only: resume after a repair (repair is build 3).",
    # runs
    "runs.start": "CLI-only: start a run from a spec file (the dashboard starts from notes).",
    "runs.status": "CLI-only: `phoenix run status`.",
    "runs.list_": "CLI-only: `phoenix run list`.",
    "runs.log": "CLI-only: `phoenix run log`.",
    "runs.summary": "CLI-only: `phoenix run summary`.",
    "runs.would_lose": "Internal: part of discard's warning.",
    # service
    "service.restart_unit": "Internal: restarts one systemd unit.",
    "service.restart": "CLI-only: `phoenix service restart`.",
    # services
    "services.used_by": "Internal: part of the services list.",
    "services.recipes": "Internal: part of the services list.",
    "services.proxy_spec_for": "Runner-only: what the key proxy lets a step reach.",
    # settings
    "settings.set": "CLI-only: `phoenix settings set` (the dashboard uses set_many).",
    "settings.change_list": "Internal: part of set_many.",
    "settings.is_safety_key": "Internal: part of set_many.",
    "settings.dry_check": "Internal: part of check.",
    # suggest
    "suggest.mode": "Internal: suggestions switch.",
    "suggest.check_key": "Internal: suggestions key check.",
    "suggest.show": "CLI-only: `phoenix suggest show`.",
    # update
    "update.release": "Internal: the newest release lookup.",
    "update.after_install": "Runner-only: runs after the updater installs.",
    "docs.resolve": "Internal: finds a document for show and download.",
    "repair.apply": "CLI-only: `phoenix repair apply` (the dashboard uses apply_text; repair is build 3).",
    "report.status": "CLI-only: `phoenix report status` (the dashboard uses report.saved).",
    # agent (the old one)
    "agent.brief": "Internal: the old agent's brief.",
}

