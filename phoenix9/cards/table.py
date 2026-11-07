"""Card: a small table of text and numbers proposed by the agent."""
from phoenix9.ops import common

schema = {"columns": "list[str]", "rows": "list"}
inline = True
MAX_COLUMNS, MAX_ROWS, MAX_CELL = 8, 50, 200


def _cell(value) -> str | int | float:
    """One cell: numbers stay numbers, text is cut to 200 characters."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise common.OpsError("Every table cell must be text or a number.")
    return value[:MAX_CELL] if isinstance(value, str) else value


def build(query: dict) -> dict:
    """The card: data is {columns, rows, footer}; bad shapes are refused with a plain reason."""
    columns, rows = query.get("columns"), query.get("rows", [])
    if not columns or len(columns) > MAX_COLUMNS:
        raise common.OpsError(f"A table card needs 1 to {MAX_COLUMNS} columns.")
    if len(rows) > MAX_ROWS:
        raise common.OpsError(f"A table card can have at most {MAX_ROWS} rows.")
    made = []
    for row in rows:
        if not isinstance(row, list):
            raise common.OpsError("Every table row must be a list of cells.")
        if len(row) != len(columns):
            raise common.OpsError("Every table row must have one cell per column.")
        made.append([_cell(c) for c in row])
    return {"title": "Table", "data": {"columns": [c[:MAX_CELL] for c in columns], "rows": made,
                                       "footer": "proposed by the agent"},
            "actions": [], "watch": {"projects": [], "runs": [], "types": []}}
