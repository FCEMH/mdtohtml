import json
import os
import tempfile
from pathlib import Path


def atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".md2html-",
            delete=False,
        ) as f:
            temp = f.name
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)


def save_report(path: Path, report):
    atomic_write(
        path, json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n"
    )
