from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..models import Document, Report


@dataclass
class FileSource:
    path: Path
    resource_root: Path | None = None
    explicitly_include: bool = False

    def __post_init__(self):
        self.path = Path(self.path).resolve()
        if self.resource_root is not None:
            self.resource_root = Path(self.resource_root).resolve()


@dataclass
class FolderSource:
    root: Path
    recursive: bool = True
    include_files: list[str] | None = None

    def __post_init__(self):
        self.root = Path(self.root).resolve()


@dataclass
class ChatGPTShareSource:
    url: str
    messages: list[ChatMessage] | None = None
    title: str | None = None


SourceSpec = FileSource | FolderSource | ChatGPTShareSource


@dataclass
class ChatMessage:
    id: str
    role: str  # "assistant" | "user" | "system" | "unknown"
    text: str
    create_time: float | None = None
    author_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreparedInput:
    root: Path
    documents: list[Document]
    origin: dict[str, Any]
    source_fingerprint: str
    temp_dir: Path | None = None  # if created for temp markdown/assets


@dataclass
class BuildRequest:
    source: SourceSpec
    output: Path | None = None
    config_path: Path | None = None
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass
class BuildResult:
    status: Literal["success", "warning", "failed", "cancelled"]
    output: Path | None = None
    artifact_written: bool = False
    report: Report = field(default_factory=Report)
    report_saved: bool | None = None
    error_message: str = ""
