# What to click

Open the dashboard at `#/agent-next` and try this list.

1. Type "show me my projects". Cards appear for the projects it finds. Click one card and the dashboard opens that project.
2. Ask it to turn build notifications on for a test project. An approval card shows the exact change. Click **Approve** and check that the switch is now on.
3. Ask for the same change again and click **Deny**. Nothing changes, and the agent says so.
4. Start a build on a test project, then ask the agent to stop it. The approval card asks you to type the build's run id (like `20261110-145115-...`). **Approve** stays off until you type it exactly. Type it, click **Approve**, and the build stops.
5. Ask it to set a key for a test project. A masked key card appears. Type the value into the masked field and save. The key shows as saved in the project's keys, and the agent only hears "saved". Try **Cancel** once too: it hears "cancelled".
6. Ask it to delete a project. It does not do it. It points you to the project's delete button in the dashboard, because deleting is for you alone.

## Agent v3 build 3: repair and resume failed builds

Use the deliberately failed demo run: project `demo-site`, run `20261022-140000-blog-section` (task 2 failed after 3 tries; task 2 also has locked checks). Open the dashboard at `#/agent-next`.

1. Open the failed run in `demo-site` (Builds, then `20261022-140000-blog-section`). It shows as failed, with task 2 and its three tries.
2. In the agent panel, ask: "Why did the blog section build fail?" The agent reads the run's events, the failing task and each try (one line per try).
3. Read the **what happened** card: the cause in plain English, what was tried, what the agent suggests, and one button per option (for example re-run task 2, skip task 2, raise max tries).
4. Click one option, for example **Raise max tries**. It does not run yet: the approval card of that control opens, showing the exact change. Click **Approve** and the repair happens. Ask for another option and click **Deny**: nothing changes and the agent says so.
5. One repair at a time: ask for a repair, and while its approval card is still open ask for a second repair on the same run. The agent says another repair for this run is already waiting for your answer or being carried out, and shows no second card. Then answer the first card (**Approve** or **Deny**) and the agent can take a new one.
6. Unsafe repair: ask the agent to "rewrite the checks of task 2 so they pass". Task 2 of this demo run has locked checks, so the agent refuses with a plain message ("That would loosen a safety check, so I can't do it. Alex can do it from the dashboard.") and no approval card opens. The agent has no tool to force a repair past locked checks; only you can, from the dashboard.
7. Open the run's events (Logs tab). Each repair you approved shows a `repair.applied` event with who `agent`; the repair you denied and the refused one are not there.

## Agent v3 build 4: guided flows

Open the dashboard at `#/agent-next`.

1. **New project.** Ask: "Make a new project." Answer the choice cards (name, type, framework, libraries and services, GitHub owner). A flow card shows the step you are on.
2. Read the **Create it?** approval card: name, type, framework, services and whether a new GitHub repo is made. Click **Approve** and watch the progress card follow the creation to its end.
3. Start another new project and click **Deny** once: nothing is created and the agent says so.
4. Start another and click **Cancel** on a choice card part-way: the flow stops and the agent says it was cancelled.
5. Start another, answer two cards, then reload the page. The flow card shows where the flow was; tell the agent to carry on and it does.
6. **Keys.** Ask it to set a key for a test project. Use the masked card to type the value and save. Then ask it to add keys from a .env file and upload a small .env that holds one name already in the project's list. The card shows that name as a conflict with **keep existing / replace**. Only names are shown, never values; comments and blank lines are skipped, and clearly public names (such as a port) are left unhidden.
7. **Hotfix.** Describe a small change. The agent writes a short brief and the approval card shows the whole brief ("start it?"). Approve to start a short build on its own branch. Ask for a second hotfix on the same project while one is going: it is refused.
8. **Build start.** Ask it to start a build: pick the project, the preset and a spec. The plan check card shows whether the plan passes. Then read the approval card and approve to start.
9. **Next-step chips.** Look at the chips after a reply. On a project with no build they offer to start one; on a failed run, "what happened"; with an open question, to answer it. Change the state and watch the chips change.
10. **Quick edits are not offered by the agent.** It has no code or file tools and Phoenix has no route to start a quick edit for it. A small change goes through the hotfix flow (step 7).
