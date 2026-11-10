# What to click

Open the dashboard at `#/agent-next` and try this list.

1. Type "show me my projects". Cards appear for the projects it finds. Click one card and the dashboard opens that project.
2. Ask it to turn build notifications on for a test project. An approval card shows the exact change. Click **Approve** and check that the switch is now on.
3. Ask for the same change again and click **Deny**. Nothing changes, and the agent says so.
4. Start a build on a test project, then ask the agent to stop it. The approval card asks you to type the build's run id (like `20261110-145115-...`). **Approve** stays off until you type it exactly. Type it, click **Approve**, and the build stops.
5. Ask it to set a key for a test project. A masked key card appears. Type the value into the masked field and save. The key shows as saved in the project's keys, and the agent only hears "saved". Try **Cancel** once too: it hears "cancelled".
6. Ask it to delete a project. It does not do it. It points you to the project's delete button in the dashboard, because deleting is for you alone.
