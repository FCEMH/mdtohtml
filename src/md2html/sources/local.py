from __future__ import annotations

import hashlib
import os
from pathlib import Path

from ..config import load_config
from ..models import BuildError, Document, Report
from ..scanner import front_matter, matches, natural, scan
from .models import FileSource, FolderSource, PreparedInput


def compute_file_fingerprint(path: Path) -> str:
    h = hashlib.sha256()
    try:
        stat = path.stat()
        h.update(f"{stat.st_size}_{stat.st_mtime_ns}".encode())
        h.update(path.read_bytes())
    except OSError:
        pass
    return h.hexdigest()


def compute_folder_fingerprint(root: Path) -> str:
    h = hashlib.sha256()
    try:
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(dirs, key=natural)
            for f in sorted(files, key=natural):
                p = Path(directory) / f
                if not p.is_symlink() and p.suffix.lower() == ".md":
                    stat = p.stat()
                    h.update(f"{p.name}_{stat.st_size}_{stat.st_mtime_ns}".encode())
    except OSError:
        pass
    return h.hexdigest()


def prepare_file_source(
    source: FileSource,
    config: dict | None = None,
    report: Report | None = None,
) -> PreparedInput:
    if report is None:
        report = Report()
    path = Path(os.path.abspath(source.path))
    if not path.exists():
        raise BuildError(f"文件不存在: {path}")
    if not path.is_file():
        raise BuildError(f"指定路径不是文件: {path}")
    if path.suffix.lower() != ".md":
        raise BuildError(f"必须选择 Markdown 文件 (.md): {path}")
    if path.is_symlink():
        raise BuildError("输入文件不能是符号链接")

    resource_root = (
        Path(os.path.abspath(source.resource_root))
        if source.resource_root is not None
        else path.parent
    )
    if not resource_root.exists() or not resource_root.is_dir():
        raise BuildError(f"资源根目录不存在: {resource_root}")
    if resource_root.is_symlink():
        raise BuildError("资源根目录不能是符号链接")
    if not path.is_relative_to(resource_root):
        raise BuildError(f"输入文件 {path} 必须位于资源根目录 {resource_root} 内")

    # Check for symlink in parent chain up to resource_root
    for part in (path, *path.parents):
        if part == resource_root:
            break
        if part.is_symlink():
            raise BuildError("文件路径不可经过符号链接")

    rel = path.relative_to(resource_root).as_posix()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as e:
        raise BuildError(f"{rel}: 不能读取 UTF-8: {e}", 2) from e

    meta, body = front_matter(text, rel)

    if config is None:
        config = load_config(resource_root)

    is_excluded = any(matches(rel, p) for p in config["content"]["exclude"])
    is_draft = bool(config["content"]["skip_draft"] and meta.get("draft", False))

    if (is_excluded or is_draft) and not source.explicitly_include:
        reason = "草稿文件" if is_draft else "被配置排除"
        report.add(
            "single_file_status",
            f"文件被标为 {reason}，但在单文件模式中已确认收录",
            source=rel,
            severity="info",
        )

    doc = Document(path=path, rel=rel, text=body, metadata=meta)
    if "title" in meta and meta["title"]:
        doc.title = str(meta["title"])

    fingerprint = compute_file_fingerprint(path)
    origin = {
        "type": "file",
        "path": str(path),
        "resource_root": str(resource_root),
        "title": doc.title or path.stem,
        "is_draft": is_draft,
        "is_excluded": is_excluded,
    }

    report.stats.update(
        documents=1,
        directories=1,
        input_markdown_bytes=path.stat().st_size,
    )

    return PreparedInput(
        root=resource_root,
        documents=[doc],
        origin=origin,
        source_fingerprint=fingerprint,
    )


def prepare_folder_source(
    source: FolderSource,
    config: dict | None = None,
    report: Report | None = None,
) -> PreparedInput:
    if report is None:
        report = Report()
    root = Path(os.path.abspath(source.root))
    if not root.exists():
        raise BuildError(f"输入目录不存在: {root}")
    if not root.is_dir():
        raise BuildError(f"输入路径不是目录: {root}")
    if root.is_symlink():
        raise BuildError("输入根目录不能是符号链接")

    if config is None:
        config = load_config(root)

    docs = scan(root, config, report)
    if source.include_files is not None:
        doc_map = {d.rel: d for d in docs}
        filtered_docs = []
        for rel in source.include_files:
            if rel in doc_map:
                filtered_docs.append(doc_map[rel])
            else:
                matched = next((d for d in docs if str(d.path) == rel or d.rel == rel or d.path.name == rel), None)
                if matched and matched not in filtered_docs:
                    filtered_docs.append(matched)
        if not filtered_docs:
            raise BuildError("未选择任何要合并的 Markdown 文件", 2)
        docs = filtered_docs
        report.stats.update(
            documents=len(docs),
            input_markdown_bytes=sum(d.path.stat().st_size for d in docs if d.path.exists()),
        )

    fingerprint = compute_folder_fingerprint(root)
    origin = {
        "type": "folder",
        "root": str(root),
        "title": config["book"]["title"] or root.name,
        "count": len(docs),
        "included_files": [d.rel for d in docs],
    }

    return PreparedInput(
        root=root,
        documents=docs,
        origin=origin,
        source_fingerprint=fingerprint,
    )
