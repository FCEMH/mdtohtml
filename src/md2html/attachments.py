"""Safe, referenced local attachments. No general HTML/PDF/script embedding."""

import base64
import hashlib
import json
from pathlib import Path

from .assets import MIMES


class Attachments:
    def __init__(self, root, assets, report):
        self.root, self.assets, self.report = root, assets, report
        self.entries = {}

    def link(self, doc, path: Path):
        if path in self.entries:
            return "#" + self.entries[path]["id"]
        relative = path.relative_to(self.root).as_posix()
        identifier = "attachment-" + hashlib.sha256(relative.encode()).hexdigest()[:20]
        entry = {"id": identifier, "name": path.name, "path": relative}
        try:
            if path.suffix.lower() in MIMES:
                uri = self.assets.encode(doc, path, count_reference=False)
                if not uri:
                    return None
                entry.update(kind="image", uri=uri)
            elif path.suffix.lower() == ".json":
                data = path.read_bytes()
                text = data.decode("utf-8-sig")
                json.loads(text)  # Reject corrupt/mislabeled JSON, never execute it.
                entry.update(
                    kind="json",
                    text=text,
                    uri="data:application/json;base64,"
                    + base64.b64encode(data).decode(),
                )
            else:
                self.report.add(
                    "unsupported_attachment",
                    f"附件存在，但暂不支持安全离线打包该类型: {relative}",
                    doc.rel,
                )
                return None
        except (OSError, UnicodeError, ValueError, RecursionError) as e:
            self.report.add(
                "invalid_attachment", f"附件读取/格式错误: {relative}: {e}", doc.rel
            )
            return None
        self.entries[path] = entry
        return "#" + identifier

    def stats(self):
        return {
            "attachments": len(self.entries),
            "json_attachments": sum(e["kind"] == "json" for e in self.entries.values()),
            "image_link_previews": sum(
                e["kind"] == "image" for e in self.entries.values()
            ),
        }
