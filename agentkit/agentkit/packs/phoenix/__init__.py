"""The Phoenix site pack: Phoenix's tools, cards and instructions for the agent."""
from agentkit.pack import Pack, ServerTool
from agentkit.packs.phoenix.client import DEFAULT_URL, PhoenixClient
from agentkit.packs.phoenix.tools import ListProjects, ShowProject, make_tools

INSTRUCTIONS = "You help Alex look after his Phoenix projects. Answer in plain English."


def build_pack(client: PhoenixClient | None = None) -> Pack:
    """Make the Phoenix pack around a client (the real Phoenix API by default)."""
    list_projects, show_project, list_runs = make_tools(client or PhoenixClient(DEFAULT_URL))
    return Pack(
        name="phoenix",
        instructions=INSTRUCTIONS,
        server_tools=(
            ServerTool("list_projects", "List projects, filtered like the Projects page.", ListProjects, "read",
                       list_projects),
            ServerTool("show_project", "Show one project.", ShowProject, "read", show_project),
            ServerTool("list_runs", "List a project's build runs.", ShowProject, "read", list_runs),
        ),
        components={"list_projects": "ProjectCards", "show_project": "ProjectCards", "list_runs": "RunCards"},
    )


PACK = build_pack()
