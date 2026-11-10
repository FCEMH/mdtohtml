from __future__ import annotations

import os
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .anchors import slug
from .models import BuildError
from .scanner import IGNORED, safe_path


def normalize(text):
    return unicodedata.normalize("NFKC", text).casefold()


class Resolver:
    def __init__(self, root, docs, config, report, attachments=None):
        self.root, self.config, self.report = root, config, report
        self.docs = {doc.path: doc for doc in docs}
        self.attachments = attachments
        self.names = defaultdict(list)
        self.files = defaultdict(list)
        self.links = 0
        available_images = set()
        for doc in docs:
            for key in {
                doc.rel,
                doc.rel[:-3],
                doc.path.name,
                doc.path.stem,
                *doc.metadata.get("aliases", []),
            }:
                self.names[normalize(key)].append(doc)
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [
                d
                for d in dirs
                if d not in IGNORED
                and not d.startswith(".")
                and not (Path(directory) / d).is_symlink()
            ]
            for name in files:
                path = Path(directory) / name
                if not path.is_symlink() and not name.startswith("."):
                    self.files[normalize(name)].append(path)
                    if path.suffix.lower() in {
                        ".png",
                        ".jpg",
                        ".jpeg",
                        ".gif",
                        ".webp",
                        ".svg",
                    }:
                        available_images.add(path)
        report.stats.update(
            discovered_images=len(available_images),
            available_image_bytes=sum(p.stat().st_size for p in available_images),
        )

    def fail(self, code, doc, target, detail):
        self.report.add(
            code,
            f"{detail}: {target}",
            doc.rel,
            suggestion="使用相对于来源文档的明确路径，或修复目标文件/标题",
        )

    def unique(self, values, doc, target):
        values = (
            list(dict.fromkeys(values))
            if all(isinstance(x, Path) for x in values)
            else list({x.rel: x for x in values}.values())
        )
        if len(values) == 1:
            return values[0]
        if len(values) > 1:
            self.fail("ambiguous_reference", doc, target, "同名引用歧义，请使用路径")
        else:
            self.fail("missing_reference", doc, target, "目标不存在或未被收录")
        return None

    def local(self, doc, name, suffix=""):
        if "\\" in name:
            raise BuildError("引用路径必须使用 / 而不是反斜杠", 2)
        path = safe_path(self.root, doc.path.parent / name)
        if suffix and not path.suffix:
            path = path.with_suffix(suffix)
        return path

    def image_path(self, doc, target, wiki=False):
        try:
            parts = urlsplit(target)
            if parts.scheme or parts.netloc:
                return self.fail(
                    "remote_image", doc, target, "远程图片未下载，以占位说明保留"
                )
            name = unquote(parts.path)
            path = self.local(doc, name)
            if path.is_file():
                return path
            if not wiki:
                return self.fail("missing_image", doc, target, "图片不存在")
            candidate = safe_path(self.root, self.root / name)
            if candidate.is_file():
                return candidate
            configured = []
            for folder in self.config["content"]["attachment_dirs"]:
                candidate = safe_path(self.root, self.root / folder / name)
                if candidate.is_file():
                    configured.append(candidate)
            if configured:
                return self.unique(configured, doc, target)
            return self.unique(
                self.files.get(normalize(Path(name).name), []), doc, target
            )
        except (BuildError, ValueError, OSError) as e:
            return self.fail("unsafe_reference", doc, target, str(e))

    def link(self, doc, target, wiki=False):
        try:
            parts = urlsplit(target)
            if parts.scheme or parts.netloc:
                if parts.scheme.lower() in (
                    "http",
                    "https",
                    "mailto",
                ) and not target.startswith("//"):
                    return target
                return self.fail("unsafe_link", doc, target, "禁止的链接协议")
            name, fragment = unquote(parts.path), unquote(parts.fragment)
            self.links += 1
            if fragment.startswith("^"):
                return self.fail(
                    "unsupported_block_reference",
                    doc,
                    target,
                    "P2 块引用未实现，保留文本",
                )
            destination = doc if not name else None
            if name:
                path = self.local(doc, name, ".md" if wiki else "")
                if path in self.docs:
                    destination = self.docs[path]
                elif wiki:
                    root_path = safe_path(self.root, self.root / name)
                    if not root_path.suffix:
                        root_path = root_path.with_suffix(".md")
                    destination = self.docs.get(root_path)
                    if destination is None:
                        destination = self.unique(
                            self.names.get(normalize(name), []), doc, target
                        )
                elif path.is_file() and path.suffix.lower() != ".md":
                    if fragment:
                        return self.fail(
                            "unsupported_attachment_fragment",
                            doc,
                            target,
                            "附件片段引用暂不支持",
                        )
                    if self.attachments is not None:
                        return self.attachments.link(doc, path)
                    return self.fail(
                        "unsupported_attachment", doc, target, "附件类型暂不支持"
                    )
                else:
                    return self.fail(
                        "missing_link",
                        doc,
                        target,
                        "目标文件不存在，或 Markdown 未被收录",
                    )
            if destination is None:
                return None
            if fragment:
                anchor = destination.anchors.get(
                    normalize(fragment)
                ) or destination.anchors.get(normalize(slug(fragment)))
                if anchor:
                    return "#" + anchor
                return self.fail("missing_heading", doc, target, "标题不存在")
            return "#" + destination.id
        except (BuildError, ValueError, OSError) as e:
            return self.fail("unsafe_reference", doc, target, str(e))
