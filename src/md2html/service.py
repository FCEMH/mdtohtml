from __future__ import annotations

import os
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from . import math_renderer, pandoc_bridge
from .config import load_config
from .html_builder import build
from .models import BuildError, Report
from .output_policy import protect_target, safe_staging_path
from .sources import (
    BuildResult,
    ChatGPTShareSource,
    FileSource,
    FolderSource,
    PreparedInput,
    SourceSpec,
    inspect_chatgpt_source,
    prepare_chatgpt_source,
    prepare_file_source,
    prepare_folder_source,
)


def check_runtime() -> dict[str, Any]:
    """Check Python environment, Pandoc, Node, KaTeX, templates, and GUI backends."""
    risks = []
    pandoc_version = ""
    node_info = {}
    templates_intact = False

    # Pandoc
    pandoc_path = pandoc_bridge.executable()
    try:
        pandoc_version = pandoc_bridge.version()
    except Exception as e:
        risks.append(f"Pandoc 不可用: {e}")

    # Node & KaTeX
    node_path = math_renderer.node_executable()
    try:
        node_info = math_renderer.probe()
    except Exception as e:
        risks.append(f"Node / KaTeX 不可用: {e}")

    # Templates
    templates = Path(__file__).parent / "templates"
    templates_intact = all(
        (templates / n).is_file()
        for n in ("reader.html.j2", "reader.css", "reader.js", "print.css")
    )
    if not templates_intact:
        risks.append("HTML 阅读器模板包不完整")

    # GUI Backend check
    gui_backend = None
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("WebKit2", "4.0")
        gui_backend = "GTK 3 (WebKit2)"
    except Exception:
        try:
            from PyQt5 import QtWebEngineWidgets  # noqa: F401
            gui_backend = "PyQt5"
        except Exception:
            try:
                from PyQt6 import QtWebEngineWidgets  # noqa: F401
                gui_backend = "PyQt6"
            except Exception:
                gui_backend = "未检测到可用 WebKit/Qt 后端（GUI 需运行环境支持）"

    status = "ready" if not risks else "error"
    return {
        "status": status,
        "python": sys.version.split()[0],
        "pandoc_path": pandoc_path,
        "pandoc_version": pandoc_version,
        "node_path": node_path,
        "node_info": node_info,
        "templates_intact": templates_intact,
        "gui_backend": gui_backend,
        "risks": risks,
    }


def suggest_output_path(source: SourceSpec, title: str = "") -> Path | None:
    """Suggest default output HTML path according to Guide Section 3 & 8."""
    if isinstance(source, FileSource):
        path = Path(source.path)
        return path.with_suffix(".html")
    elif isinstance(source, FolderSource):
        root = Path(source.root)
        return root.parent / f"{root.name}.html"
    elif isinstance(source, ChatGPTShareSource):
        return None
    return Path.cwd() / "output.html"


def build_file_tree(docs: list[Any], root: Path) -> list[dict[str, Any]]:
    """Build a nested tree structure for documents in folder / file mode with folders first."""
    tree: list[dict[str, Any]] = []
    for doc in docs:
        parts = Path(doc.rel).parts
        current_level = tree
        for part in parts[:-1]:
            found = next((item for item in current_level if item.get("type") == "dir" and item.get("name") == part), None)
            if not found:
                found = {"type": "dir", "name": part, "children": []}
                current_level.append(found)
            current_level = found["children"]
        try:
            stat = doc.path.stat() if doc.path.exists() else None
            size = stat.st_size if stat else 0
            mtime = stat.st_mtime if stat else 0
        except OSError:
            size, mtime = 0, 0
        current_level.append({
            "type": "file",
            "name": parts[-1],
            "rel": doc.rel,
            "title": doc.title or parts[-1],
            "size": size,
            "mtime": mtime,
        })

    def sort_level(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        dirs = [item for item in items if item.get("type") == "dir"]
        files = [item for item in items if item.get("type") == "file"]
        for d in dirs:
            if "children" in d:
                d["children"] = sort_level(d["children"])
        return dirs + files

    return sort_level(tree)


def inspect_source(
    source: SourceSpec,
    config_path: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect source and return summary, file tree/messages, and suggested output."""
    report = Report()
    if isinstance(source, FileSource):
        res_root = source.resource_root or Path(source.path).parent
        config = load_config(res_root, config_path, overrides)
        prepared = prepare_file_source(source, config, report)
        title = Path(source.path).stem
        tree = build_file_tree(prepared.documents, prepared.root)
        stats = {
            "documents": 1,
            "directories": 1,
            "size_bytes": prepared.documents[0].path.stat().st_size,
        }
        suggested_out = suggest_output_path(source, title)
        return {
            "type": "file",
            "title": title,
            "root": str(prepared.root),
            "resource_root": str(prepared.root),
            "source_path": str(source.path),
            "suggested_output": str(suggested_out) if suggested_out else "",
            "stats": stats,
            "tree": tree,
            "origin": prepared.origin,
            "issues": [i.__dict__ for i in report.issues],
            "config": config,
        }

    elif isinstance(source, FolderSource):
        config = load_config(source.root, config_path, overrides)
        prepared = prepare_folder_source(source, config, report)
        title = source.root.name
        tree = build_file_tree(prepared.documents, source.root)
        dirs = {str(Path(d.rel).parent) for d in prepared.documents if str(Path(d.rel).parent) != "."}
        stats = {
            "documents": len(prepared.documents),
            "directories": len(dirs),
            "size_bytes": sum(d.path.stat().st_size for d in prepared.documents if d.path.exists()),
        }
        suggested_out = suggest_output_path(source, title)
        return {
            "type": "folder",
            "title": title,
            "root": str(source.root),
            "suggested_output": str(suggested_out) if suggested_out else "",
            "stats": stats,
            "tree": tree,
            "origin": prepared.origin,
            "issues": [i.__dict__ for i in report.issues],
            "config": config,
        }

    elif isinstance(source, ChatGPTShareSource):
        info = inspect_chatgpt_source(source)
        tree = [
            {
                "type": "message",
                "id": m["id"],
                "role": m["role"],
                "name": f"消息 {i+1} · {m['role']}",
                "snippet": m["snippet"],
                "chars": m["chars"],
            }
            for i, m in enumerate(info["messages"])
        ]
        stats = {
            "documents": 1,
            "directories": 0,
            "message_count": info["message_count"],
            "assistant_count": info["assistant_count"],
            "user_count": info["user_count"],
            "total_chars": info["total_chars"],
        }
        return {
            "type": "chatgpt",
            "title": info["title"],
            "suggested_output": "",
            "stats": stats,
            "tree": tree,
            "origin": info,
            "issues": [],
            "config": deepcopy(load_config(Path.cwd())),
        }
    else:
        raise BuildError(f"未知来源类型: {type(source)}")


def prepare_source(
    source: SourceSpec,
    config: dict[str, Any],
    report: Report,
) -> PreparedInput:
    """Prepare input for build pipeline."""
    if isinstance(source, FileSource):
        return prepare_file_source(source, config, report)
    elif isinstance(source, FolderSource):
        return prepare_folder_source(source, config, report)
    elif isinstance(source, ChatGPTShareSource):
        return prepare_chatgpt_source(source, report)
    else:
        raise BuildError(f"未知来源类型: {type(source)}")


def check_content(
    source: SourceSpec,
    config_path: Path | None = None,
    overrides: dict[str, Any] | None = None,
) -> BuildResult:
    """Run full check without writing output HTML."""
    report = Report()
    try:
        # Determine config root
        if isinstance(source, FileSource):
            root = source.resource_root or Path(source.path).parent
        elif isinstance(source, FolderSource):
            root = source.root
        else:
            root = Path.cwd()

        config = load_config(root, config_path, overrides)
        prepared = prepare_source(source, config, report)
        build(
            prepared.root,
            config,
            report,
            output=None,
            documents=prepared.documents,
        )
        if prepared.temp_dir and prepared.temp_dir.exists():
            shutil.rmtree(prepared.temp_dir, ignore_errors=True)

        status = "warning" if any(i.severity == "warning" for i in report.issues) else "success"
        return BuildResult(
            status=status,
            output=None,
            artifact_written=False,
            report=report,
        )
    except BuildError as e:
        report.status, report.exit_code = "failed", e.code
        report.add("fatal", str(e), severity="error")
        return BuildResult(status="failed", report=report, error_message=str(e))
    except Exception as e:
        report.status, report.exit_code = "failed", 1
        report.add("io_error", str(e), severity="error")
        return BuildResult(status="failed", report=report, error_message=str(e))


def build_service(
    source: SourceSpec,
    output: Path | None = None,
    config_path: Path | None = None,
    overrides: dict[str, Any] | None = None,
    job_id: str = "default",
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    cancel_token: Any = None,
) -> BuildResult:
    """Shared build execution for CLI, worker, and GUI."""
    report = Report()
    prepared: PreparedInput | None = None
    staging_file: Path | None = None

    try:
        # Determine config root
        if isinstance(source, FileSource):
            root = source.resource_root or Path(source.path).parent
        elif isinstance(source, FolderSource):
            root = source.root
        else:
            root = Path.cwd()

        config = load_config(root, config_path, overrides)
        if on_progress:
            on_progress({"stage": "prepare", "current": 0, "total": 1, "message": "正在准备输入内容..."})

        prepared = prepare_source(source, config, report)

        # Protect output path
        final_output: Path | None = None
        if output is not None:
            final_output = protect_target(output, prepared.root, ".html")
            staging_file = safe_staging_path(final_output, job_id)

        build(
            prepared.root,
            config,
            report,
            output=staging_file if final_output else None,
            documents=prepared.documents,
            on_progress=on_progress,
            cancel_token=cancel_token,
        )

        # Atomic commit from staging to final
        if final_output and staging_file and staging_file.exists():
            if cancel_token and getattr(cancel_token, "cancelled", False):
                staging_file.unlink(missing_ok=True)
                raise BuildError("构建已取消", 0)
            # Re-verify target before commit
            protect_target(final_output, prepared.root, ".html")
            os.replace(staging_file, final_output)
            staging_file = None

        status = "warning" if any(i.severity == "warning" for i in report.issues) else "success"
        return BuildResult(
            status=status,
            output=final_output,
            artifact_written=bool(final_output and final_output.exists()),
            report=report,
        )

    except BuildError as e:
        if staging_file and staging_file.exists():
            staging_file.unlink(missing_ok=True)
        report.status, report.exit_code = "failed", e.code
        report.add("fatal", str(e), severity="error")
        is_cancel = getattr(cancel_token, "cancelled", False) or "取消" in str(e)
        return BuildResult(
            status="cancelled" if is_cancel else "failed",
            report=report,
            error_message=str(e),
        )
    except Exception as e:
        if staging_file and staging_file.exists():
            staging_file.unlink(missing_ok=True)
        report.status, report.exit_code = "failed", 1
        report.add("system_error", str(e), severity="error")
        return BuildResult(
            status="failed",
            report=report,
            error_message=str(e),
        )
    finally:
        if prepared and prepared.temp_dir and prepared.temp_dir.exists():
            shutil.rmtree(prepared.temp_dir, ignore_errors=True)
        if staging_file and staging_file.exists():
            staging_file.unlink(missing_ok=True)
