from __future__ import annotations

import fnmatch
import math
import os
import re
from pathlib import Path

import yaml

from .models import BuildError, Document, Report

IGNORED = {".git", ".obsidian", "node_modules", "dist", "build", "__pycache__"}


def natural(text: str) -> tuple:
    return tuple(
        (1, int(p)) if p.isdigit() else (0, p.casefold())
        for p in re.split(r"(\d+)", text)
    )


def matches(rel: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(rel, pattern) or (
        pattern.startswith("**/") and fnmatch.fnmatchcase(rel, pattern[3:])
    )


def safe_path(root: Path, path: Path) -> Path:
    """Reject traversal AND symlinks, including a link that happens to stay in root."""
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(root):
        raise BuildError("引用越过输入根目录", 2)
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink():
            raise BuildError("不允许符号链接资源", 2)
    if not path.resolve().is_relative_to(root):
        raise BuildError("引用越过输入根目录", 2)
    return path


def front_matter(text: str, source: str) -> tuple[dict, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = next(
        (i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None
    )
    if end is None:
        raise BuildError(f"{source}: front matter 缺少结束分隔符", 2)
    try:
        meta = yaml.safe_load("".join(lines[1:end])) or {}
    except yaml.YAMLError as e:
        raise BuildError(f"{source}: front matter 无效: {e}", 2) from e
    if not isinstance(meta, dict):
        raise BuildError(f"{source}: front matter 必须为映射", 2)
    if "title" in meta and not isinstance(meta["title"], str):
        raise BuildError(f"{source}: title 必须为字符串", 2)
    if "nav_order" in meta and (
        not isinstance(meta["nav_order"], (int, float))
        or isinstance(meta["nav_order"], bool)
        or not math.isfinite(meta["nav_order"])
    ):
        raise BuildError(f"{source}: nav_order 必须为数值", 2)
    if "draft" in meta and type(meta["draft"]) is not bool:
        raise BuildError(f"{source}: draft 必须为布尔值", 2)
    if "aliases" in meta:
        if isinstance(meta["aliases"], str):
            meta["aliases"] = [meta["aliases"]]
        if not isinstance(meta["aliases"], list) or not all(
            isinstance(x, str) for x in meta["aliases"]
        ):
            raise BuildError(f"{source}: aliases 必须为字符串列表", 2)
    return meta, "".join(lines[end + 1 :])


def scan(root: Path, config: dict, report: Report) -> list[Document]:
    if not root.is_dir():
        raise BuildError(f"输入目录不存在: {root}")
    docs = []

    def onerror(error):
        raise BuildError(f"无法遍历输入目录: {error}", 2)

    for directory, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        dirs[:] = sorted(
            (
                d
                for d in dirs
                if not d.startswith(".")
                and d not in IGNORED
                and not (Path(directory) / d).is_symlink()
            ),
            key=natural,
        )
        for name in files:
            path = Path(directory) / name
            rel = path.relative_to(root).as_posix()
            if (
                name.startswith(".")
                or path.suffix.lower() != ".md"
                or path.is_symlink()
            ):
                continue
            if not any(matches(rel, p) for p in config["content"]["include"]):
                continue
            if any(matches(rel, p) for p in config["content"]["exclude"]):
                continue
            try:
                text = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError) as e:
                raise BuildError(f"{rel}: 不能读取 UTF-8: {e}", 2) from e
            meta, body = front_matter(text, rel)
            if config["content"]["skip_draft"] and meta.get("draft", False):
                continue
            docs.append(Document(path, rel, body, meta))
    # Order directories as groups, and files within their siblings. An explicit
    # descendant gives its parent group the same priority without flattening it.
    order = {x.rstrip("/"): i for i, x in enumerate(config["content"]["order"])}

    def priority(prefix: str) -> float:
        return min(
            (i for p, i in order.items() if p == prefix or p.startswith(prefix + "/")),
            default=float("inf"),
        )

    def ordered(group: list[Document], depth: int = 0) -> list[Document]:
        entries: dict[str, list[Document]] = {}
        for doc in group:
            entries.setdefault(doc.rel.split("/")[depth], []).append(doc)

        def key(item):
            name, children = item
            prefix = "/".join(children[0].rel.split("/")[: depth + 1])
            nav = (
                children[0].metadata.get("nav_order", float("inf"))
                if len(children[0].rel.split("/")) == depth + 1
                else float("inf")
            )
            return priority(prefix), nav, natural(name), name

        result = []
        for _, children in sorted(entries.items(), key=key):
            result.extend(
                children
                if len(children[0].rel.split("/")) == depth + 1
                else ordered(children, depth + 1)
            )
        return result

    docs = ordered(docs) if docs else []
    directories = {
        str(parent)
        for d in docs
        for parent in Path(d.rel).parents
        if str(parent) != "."
    }
    report.stats.update(
        documents=len(docs),
        directories=len(directories),
        input_markdown_bytes=sum(d.path.stat().st_size for d in docs),
    )
    if not docs:
        raise BuildError("未找到可构建的 Markdown（检查 include / exclude / draft）", 2)
    return docs


def scan_single_file(
    path: Path,
    resource_root: Path,
    config: dict,
    report: Report,
    explicitly_include: bool = True,
) -> list[Document]:
    path = Path(os.path.abspath(path))
    resource_root = Path(os.path.abspath(resource_root))
    if not path.is_file():
        raise BuildError(f"输入文件不存在: {path}", 2)
    if path.suffix.lower() != ".md":
        raise BuildError(f"必须是 Markdown 文件: {path}", 2)
    if not path.is_relative_to(resource_root):
        raise BuildError("文件超出资源根目录", 2)
    rel = path.relative_to(resource_root).as_posix()
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as e:
        raise BuildError(f"{rel}: 不能读取 UTF-8: {e}", 2) from e
    meta, body = front_matter(text, rel)
    if not explicitly_include:
        if config["content"]["skip_draft"] and meta.get("draft", False):
            raise BuildError(f"{rel}: 文件被标记为草稿", 2)
        if any(matches(rel, p) for p in config["content"]["exclude"]):
            raise BuildError(f"{rel}: 文件被排除规则排除", 2)
    doc = Document(path, rel, body, meta)
    report.stats.update(
        documents=1,
        directories=1,
        input_markdown_bytes=path.stat().st_size,
    )
    return [doc]

