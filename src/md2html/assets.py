import base64
import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

MIMES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


class Assets:
    def __init__(self, root, config, report):
        self.root, self.config, self.report = root, config, report
        self.hashes = {}
        self.references = 0
        self.bytes = 0
        self.embedded_bytes = 0
        self.loaded_references = 0
        self.reference_hashes = set()

    def encode(self, doc, path: Path, count_reference=True):
        mime = MIMES.get(path.suffix.lower())
        if mime is None:
            self.report.add(
                "unsupported_asset", f"未支持的图片类型: {path.name}", doc.rel
            )
            return None
        data = path.read_bytes()
        signatures = {
            "image/png": b"\x89PNG\r\n\x1a\n",
            "image/jpeg": b"\xff\xd8\xff",
            "image/gif": b"GIF",
            "image/webp": b"RIFF",
        }
        invalid = mime in signatures and not data.startswith(signatures[mime])
        if mime == "image/svg+xml":
            try:
                svg = ET.fromstring(data)
                invalid = svg.tag.split("}")[-1] != "svg"
                for node in svg.iter():
                    if node.tag.split("}")[-1] in ("script", "foreignObject"):
                        invalid = True
                    for key, value in node.attrib.items():
                        if key.lower().startswith("on") or (
                            key.split("}")[-1] in ("href", "src")
                            and not value.startswith(("#", "data:image/"))
                        ):
                            invalid = True
                svg_text = data.decode("utf-8-sig")
                if re.search(r"@import", svg_text, re.IGNORECASE) or any(
                    not u.strip(" \"'").startswith(("data:", "#"))
                    for u in re.findall(r"url\(([^)]+)\)", svg_text, re.IGNORECASE)
                ):
                    invalid = True
            except (ET.ParseError, UnicodeError):
                invalid = True
        if invalid:
            self.report.add(
                "invalid_image",
                f"图片格式错误或 SVG 含不安全/外部依赖: {path.name}",
                doc.rel,
            )
            return None
        self.embedded_bytes += len(data)
        digest = hashlib.sha256(data).hexdigest()
        if count_reference:
            self.loaded_references += 1
            self.reference_hashes.add(digest)
        if digest not in self.hashes:
            self.hashes[digest] = len(data)
            self.bytes += len(data)
        if len(data) > self.config["limits"]["warn_image_mb"] * 1024**2:
            self.report.add(
                "large_image", f"大图 {path.name}: {len(data)} bytes", doc.rel
            )
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"

    def stats(self):
        return {
            "image_references": self.references,
            "unique_images": len(self.hashes),
            "duplicate_image_references": max(
                0, self.loaded_references - len(self.reference_hashes)
            ),
            "asset_bytes": self.bytes,
            "embedded_image_bytes": self.embedded_bytes,
        }
