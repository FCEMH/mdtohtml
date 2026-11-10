from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .service import build_service
from .sources import ChatGPTShareSource, FileSource, FolderSource


def emit(data: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            emit({"event": "error", "message": "未收到任务请求数据"})
            return 1
        req = json.loads(raw_input)
    except Exception as e:
        emit({"event": "error", "message": f"请求解析失败: {e}"})
        return 1

    job_id = req.get("job_id", "default_job")
    source_type = req.get("source_type")
    source_data = req.get("source_data", {})
    output_path = Path(req["output"]) if req.get("output") else None
    config_path = Path(req["config_path"]) if req.get("config_path") else None
    overrides = req.get("overrides", {})

    source_spec = None
    if source_type == "file":
        source_spec = FileSource(
            path=Path(source_data["path"]),
            resource_root=Path(source_data["resource_root"]) if source_data.get("resource_root") else None,
            explicitly_include=source_data.get("explicitly_include", False),
        )
    elif source_type == "folder":
        source_spec = FolderSource(
            root=Path(source_data["root"]),
            recursive=source_data.get("recursive", True),
            include_files=source_data.get("include_files"),
        )
    elif source_type == "chatgpt":
        source_spec = ChatGPTShareSource(url=source_data["url"])
    else:
        emit({"event": "error", "job_id": job_id, "message": f"未知来源类型: {source_type}"})
        return 1

    def on_progress(p: dict[str, Any]) -> None:
        emit({
            "event": "progress",
            "job_id": job_id,
            **p,
        })

    result = build_service(
        source=source_spec,
        output=output_path,
        config_path=config_path,
        overrides=overrides,
        job_id=job_id,
        on_progress=on_progress,
    )

    emit({
        "event": "result",
        "job_id": job_id,
        "status": result.status,
        "output": str(result.output) if result.output else None,
        "artifact_written": result.artifact_written,
        "error_message": result.error_message,
        "report": result.report.as_dict(),
    })

    return 0 if result.status in ("success", "warning") else 1


if __name__ == "__main__":
    sys.exit(main())
