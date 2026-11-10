from __future__ import annotations

import json
import os
from pathlib import Path

from .models import BuildError


def protect_target(path: Path | str, root: Path, suffix: str) -> Path:
    """Validate and protect an output file path from overwriting source files or traversing symlinks."""
    path = Path(os.path.abspath(path))
    if path.suffix.lower() != suffix.lower():
        raise BuildError(f"输出必须为 {suffix}: {path}")
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise BuildError("输出路径不可经过符号链接")
    if path.is_relative_to(root) and any(
        p.startswith(".") for p in path.relative_to(root).parts
    ):
        raise BuildError("禁止写入输入目录的隐藏配置")
    if path.exists() and path.is_relative_to(root):
        if suffix == ".html":
            try:
                generated = path.read_text(encoding="utf-8").startswith(
                    "<!doctype html>\n<!-- md2html-generated -->"
                )
            except (OSError, UnicodeError):
                generated = False
        else:
            try:
                generated = (
                    json.loads(path.read_text(encoding="utf-8")).get("generator")
                    == "md2html"
                )
            except (ValueError, AttributeError, OSError, UnicodeError):
                generated = False
        if not generated:
            raise BuildError(f"拒绝覆盖输入目录内的原始文件: {path}")
    return path


def safe_staging_path(target: Path, job_id: str) -> Path:
    """Generate a temporary staging path in the same parent directory to ensure atomic replace."""
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    return parent / f".staging.{job_id}_{target.name}"
