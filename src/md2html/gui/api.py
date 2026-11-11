from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

from ..jobs import job_manager
from ..service import (
    check_content,
    check_runtime,
    inspect_source,
    preview_chat_messages_service,
    preview_source_service,
    render_markdown_preview_service,
    save_markdown_service,
)
from ..sources import ChatMessage, ChatGPTShareSource, FileSource, FolderSource
from .settings import load_gui_settings, save_gui_settings


class BridgeAPI:
    def __init__(self, window: Any = None):
        self.window = window

    def set_window(self, window: Any) -> None:
        self.window = window

    def check_environment(self) -> dict[str, Any]:
        """Check system and runtime dependencies."""
        return check_runtime()

    def load_settings(self) -> dict[str, Any]:
        """Load persistent GUI settings."""
        return load_gui_settings()

    def save_settings(self, settings: dict[str, Any]) -> bool:
        """Save persistent GUI settings."""
        save_gui_settings(settings)
        return True

    def choose_file(self, title: str = "选择 Markdown 文件", default_path: str = "") -> str | None:
        """Open native system file dialog to choose a markdown file."""
        if not self.window:
            return None
        import webview
        try:
            start_dir = default_path if default_path and Path(default_path).exists() else ""
            res = self.window.create_file_dialog(
                webview.OPEN_DIALOG,
                directory=start_dir,
                file_types=("Markdown (*.md)", "All files (*.*)"),
            )
            if res:
                chosen = res[0] if isinstance(res, (list, tuple)) else res
                if chosen:
                    return str(chosen)
        except Exception as e:
            print(f"[GUI] choose_file error: {e}", file=sys.stderr)
        return None

    def choose_folder(self, title: str = "选择笔记文件夹", default_path: str = "") -> str | None:
        """Open native system folder dialog to choose a directory."""
        if not self.window:
            return None
        import webview
        try:
            start_dir = default_path if default_path and Path(default_path).exists() else ""
            res = self.window.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=start_dir,
            )
            if res:
                chosen = res[0] if isinstance(res, (list, tuple)) else res
                if chosen:
                    return str(chosen)
        except Exception as e:
            print(f"[GUI] choose_folder error: {e}", file=sys.stderr)
        return None

    def choose_save_file(self, title: str = "另存为 HTML", default_filename: str = "textbook.html", default_dir: str = "") -> str | None:
        """Open native save file dialog."""
        if not self.window:
            return None
        import webview
        try:
            start_dir = default_dir if default_dir and Path(default_dir).exists() else ""
            res = self.window.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=start_dir,
                save_filename=default_filename,
                file_types=("HTML Document (*.html)", "All files (*.*)"),
            )
            if res:
                chosen = res if isinstance(res, str) else res[0]
                if chosen:
                    if not chosen.lower().endswith(".html"):
                        chosen = f"{chosen}.html"
                    save_gui_settings({"last_output_dir": str(Path(chosen).parent)})
                    return str(chosen)
        except Exception as e:
            print(f"[GUI] choose_save_file error: {e}", file=sys.stderr)
        return None

    def choose_save_markdown_file(self, title: str = "另存 Markdown", default_filename: str = "document.md", default_dir: str = "") -> str | None:
        """Open native save file dialog for markdown."""
        if not self.window:
            return None
        import webview
        try:
            start_dir = default_dir if default_dir and Path(default_dir).exists() else ""
            res = self.window.create_file_dialog(
                webview.SAVE_DIALOG,
                directory=start_dir,
                save_filename=default_filename,
                file_types=("Markdown (*.md)", "All files (*.*)"),
            )
            if res:
                chosen = res if isinstance(res, str) else res[0]
                if chosen:
                    if not chosen.lower().endswith(".md"):
                        chosen = f"{chosen}.md"
                    save_gui_settings({"last_output_dir": str(Path(chosen).parent)})
                    return str(chosen)
        except Exception as e:
            print(f"[GUI] choose_save_markdown_file error: {e}", file=sys.stderr)
        return None

    def inspect(self, source_type: str, path_or_url: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Inspect source content and return tree, stats, and metadata."""
        options = options or {}
        try:
            if source_type == "file":
                path = Path(path_or_url)
                res_root = Path(options["resource_root"]) if options.get("resource_root") else None
                source = FileSource(path=path, resource_root=res_root)
            elif source_type == "folder":
                source = FolderSource(
                    root=Path(path_or_url),
                    include_files=options.get("include_files"),
                )
            elif source_type == "chatgpt":
                source = ChatGPTShareSource(url=path_or_url)
            else:
                return {"success": False, "error": f"未知来源类型: {source_type}"}

            config_path = Path(options["config_path"]) if options.get("config_path") else None
            overrides = options.get("overrides", {})
            info = inspect_source(source, config_path=config_path, overrides=overrides)
            return {"success": True, "data": info}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def check_only(self, source_type: str, path_or_url: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run dry-run check without building output HTML."""
        options = options or {}
        try:
            if source_type == "file":
                path = Path(path_or_url)
                res_root = Path(options["resource_root"]) if options.get("resource_root") else None
                source = FileSource(path=path, resource_root=res_root)
            elif source_type == "folder":
                source = FolderSource(
                    root=Path(path_or_url),
                    include_files=options.get("include_files"),
                )
            elif source_type == "chatgpt":
                msgs = None
                if options.get("messages") is not None:
                    msgs = [
                        ChatMessage(
                            id=m.get("id", f"msg-{i}"),
                            role=m.get("role", "unknown"),
                            text=m.get("text", ""),
                            author_name=m.get("author_name"),
                        )
                        for i, m in enumerate(options["messages"])
                    ]
                source = ChatGPTShareSource(
                    url=path_or_url,
                    messages=msgs,
                    title=options.get("title"),
                )
            else:
                return {"success": False, "error": f"未知来源类型: {source_type}"}

            config_path = Path(options["config_path"]) if options.get("config_path") else None
            overrides = options.get("overrides", {})
            result = check_content(source, config_path=config_path, overrides=overrides)
            return {
                "success": True,
                "data": {
                    "status": result.status,
                    "report": result.report.as_dict(),
                    "error_message": result.error_message,
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def render_markdown_preview(self, markdown: str) -> dict[str, Any]:
        """Render markdown text with Pandoc and KaTeX for real-time preview."""
        return render_markdown_preview_service(markdown)

    def preview_content(self, source_type: str, path_or_url: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Generate in-memory HTML preview for any source type (file, folder, chatgpt)."""
        options = options or {}
        try:
            if source_type == "file":
                path = Path(path_or_url)
                res_root = Path(options["resource_root"]) if options.get("resource_root") else None
                source = FileSource(
                    path=path,
                    resource_root=res_root,
                    explicitly_include=options.get("explicitly_include", False),
                )
            elif source_type == "folder":
                source = FolderSource(
                    root=Path(path_or_url),
                    include_files=options.get("include_files"),
                )
            elif source_type == "chatgpt":
                msgs = None
                if options.get("messages") is not None:
                    msgs = [
                        ChatMessage(
                            id=m.get("id", f"msg-{i}"),
                            role=m.get("role", "unknown"),
                            text=m.get("text", ""),
                            author_name=m.get("author_name"),
                        )
                        for i, m in enumerate(options["messages"])
                    ]
                source = ChatGPTShareSource(
                    url=path_or_url,
                    messages=msgs,
                    title=options.get("title"),
                )
            else:
                return {"success": False, "error": f"未知来源类型: {source_type}"}

            config_path = Path(options["config_path"]) if options.get("config_path") else None
            overrides = options.get("overrides", {})
            return preview_source_service(source, config_path=config_path, overrides=overrides)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def preview_chat_messages(self, title: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Format and preview merged chat messages."""
        try:
            chat_messages = [
                ChatMessage(
                    id=m.get("id", f"msg-{i}"),
                    role=m.get("role", "unknown"),
                    text=m.get("text", ""),
                    author_name=m.get("author_name"),
                )
                for i, m in enumerate(messages)
            ]
            return preview_chat_messages_service(title, chat_messages)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def save_markdown(self, target_path: str, title: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Save selected/edited chat messages as a standalone markdown file with companion images."""
        try:
            chat_messages = [
                ChatMessage(
                    id=m.get("id", f"msg-{i}"),
                    role=m.get("role", "unknown"),
                    text=m.get("text", ""),
                    author_name=m.get("author_name"),
                )
                for i, m in enumerate(messages)
            ]
            return save_markdown_service(Path(target_path), title, chat_messages)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def start_build(self, request_data: dict[str, Any]) -> dict[str, Any]:
        """Start background build job."""
        try:
            job_id = job_manager.start_job(request_data)
            return {"success": True, "job_id": job_id}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_job_status(self, job_id: str) -> dict[str, Any]:
        """Query status and progress of a background job."""
        info = job_manager.get_job(job_id)
        if not info:
            return {"found": False}
        return {"found": True, **info}

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        """Cancel a running job."""
        ok = job_manager.cancel_job(job_id)
        return {"success": ok}

    def open_result(self, job_id: str, action: str = "file") -> dict[str, Any]:
        """Open generated HTML file or containing folder using system browser / file manager."""
        info = job_manager.get_job(job_id)
        if not info or not info.get("result"):
            return {"success": False, "error": "任务结果不存在"}
        output_str = info["result"].get("output")
        if not output_str:
            return {"success": False, "error": "任务未产生输出文件"}

        output_path = Path(output_str)
        if not output_path.exists():
            return {"success": False, "error": f"文件不存在: {output_path}"}

        try:
            if action == "folder":
                target_folder = output_path.parent
                if sys.platform.startswith("linux"):
                    subprocess.Popen(["xdg-open", str(target_folder)])
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(target_folder)])
                elif sys.platform == "win32":
                    os.startfile(str(target_folder))
                else:
                    webbrowser.open(target_folder.as_uri())
            else:
                # Open HTML file with default browser
                webbrowser.open(output_path.as_uri())
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": f"无法打开目标: {e}"}
