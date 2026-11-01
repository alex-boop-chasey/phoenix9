"""What a step receives (StepContext) and what it hands back (StepResult); docs/architecture.md 4.4."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

RESULT_STATUSES = ("pass", "fail", "skip", "gate")


@dataclass
class StepResult:
    """How a step ended: pass, fail, skip or gate, plus reasons, produced things and the gate to open."""
    status: str
    reasons: list[str] = field(default_factory=list)
    produces: dict = field(default_factory=dict)
    gate: dict | None = None

    def __post_init__(self):
        if self.status not in RESULT_STATUSES:
            raise ValueError(f"bad step result {self.status!r}; use one of {', '.join(RESULT_STATUSES)}")
        self.reasons = list(self.reasons)
        self.produces = dict(self.produces)


@dataclass
class ProjectInfo:
    """The project a run belongs to: name, folders, its phoenix.toml and its profile."""
    name: str
    dir: Path
    code_dir: Path
    settings: dict = field(default_factory=dict)
    profile: dict = field(default_factory=dict)


@dataclass
class RunInfo:
    """The run: id, folder and the spec as plain data (the spec.json shape)."""
    id: str
    folder: Path
    spec: dict = field(default_factory=dict)


@dataclass
class StepInfo:
    """The step as configured for this run: its own settings and, for AI steps, its ai block."""
    name: str
    kind: str
    folder: Path | None = None
    settings: dict = field(default_factory=dict)
    ai: dict = field(default_factory=dict)
    produces: tuple = ()


@dataclass
class StepContext:
    """Everything one step call can use."""
    project: ProjectInfo
    run: RunInfo
    step: StepInfo
    task: dict | None
    attempt: int
    worktree: Path | None
    things: dict
    adapters: Any
    emit: Callable[..., Any]
    log: Callable[[str], None]
    answer: dict | None = None   # the gate answer {action, note, who} when Alex sent this step back


class UsageLimit(Exception):
    """Claude's usage limit was hit; the service loop pauses the run and waits (it never switches model)."""

    def __init__(self, result):
        """Keep the session result (it may say when the limit resets)."""
        super().__init__("Claude's usage limit was reached")
        self.result = result
