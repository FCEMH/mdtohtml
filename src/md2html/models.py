from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class BuildError(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


@dataclass
class Issue:
    code: str
    message: str
    source: str = ""
    line: int | None = None
    severity: str = "warning"
    suggestion: str = ""


@dataclass
class Report:
    generator: str = "md2html"
    issues: list[Issue] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    exit_code: int = 0

    def add(self, code: str, message: str, source: str = "", **kwargs: Any) -> None:
        self.issues.append(Issue(code, message, source, **kwargs))

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Document:
    path: Path
    rel: str
    text: str
    metadata: dict
    title: str = ""
    id: str = ""
    ast: dict = field(default_factory=dict)
    headings: list[dict] = field(default_factory=list)
    anchors: dict[str, str] = field(default_factory=dict)
    anchor_ids: set[str] = field(default_factory=set)
    html: str = ""
