from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlsplit

from ..models import Document, Report
from .fetch import MAX_ASSET_BYTES, fetch_url, is_safe_url
from .models import ChatMessage


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", name).strip()
    return cleaned or "document"


def localize_images(
    markdown: str,
    images_dir: Path,
    report: Report,
) -> str:
    """Find remote images in markdown, download them safely to images_dir, and replace URLs with relative paths."""
    images_dir.mkdir(parents=True, exist_ok=True)
    img_pattern = re.compile(r"!\[(.*?)\]\((https?://[^\s\)]+)\)")
    downloaded_cache: dict[str, str] = {}

    def repl(m: re.Match) -> str:
        alt = m.group(1)
        url = m.group(2)
        if url in downloaded_cache:
            return f"![{alt}]({downloaded_cache[url]})"

        allowed_domains = (
            "openai.com",
            "chatgpt.com",
            "oaiusercontent.com",
            "windows.net",  # blob.core.windows.net used by OpenAI
            "githubusercontent.com",
        )

        try:
            if not is_safe_url(url, allowed_hosts=allowed_domains):
                report.add(
                    "remote_image_rejected",
                    f"跳过非受信域名的远程图片: {url}",
                    severity="warning",
                )
                return m.group(0)

            data, content_type = fetch_url(
                url,
                max_bytes=MAX_ASSET_BYTES,
                timeout=10,
                allowed_hosts=allowed_domains,
            )

            # Determine extension
            ext = ""
            if content_type:
                clean_type = content_type.split(";")[0].strip().lower()
                ext = mimetypes.guess_extension(clean_type) or ""
            if not ext:
                path_part = urlsplit(url).path
                ext = Path(path_part).suffix.lower()
            if ext in (".jpeg", ".jpe"):
                ext = ".jpg"
            if ext not in (".png", ".jpg", ".webp", ".svg", ".gif"):
                ext = ".png"

            url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
            filename = f"img_{url_hash}{ext}"
            file_path = images_dir / filename
            file_path.write_bytes(data)

            rel_path = f"images/{filename}"
            downloaded_cache[url] = rel_path
            return f"![{alt}]({rel_path})"
        except Exception as e:
            report.add(
                "image_download_failed",
                f"远程图片下载失败 ({e}): {url}",
                severity="warning",
            )
            return m.group(0)

    return img_pattern.sub(repl, markdown)


def messages_to_markdown(
    messages: list[ChatMessage],
    title: str,
    target_dir: Path,
    report: Report,
) -> tuple[Document, Path]:
    """Normalize ChatGPT messages into a single Markdown file with front matter."""
    target_dir.mkdir(parents=True, exist_ok=True)
    images_dir = target_dir / "images"

    effective_title = title.strip()
    if not effective_title and messages:
        # Check first line of first message
        first_line = messages[0].text.strip().splitlines()[0] if messages[0].text.strip() else ""
        if first_line.startswith("#"):
            effective_title = first_line.lstrip("#").strip()
        else:
            effective_title = first_line[:40].strip() or "AI分享内容"

    sections: list[str] = []

    # If single message from assistant
    if len(messages) == 1 and messages[0].role == "assistant":
        body = messages[0].text.strip()
        # If body already starts with an H1 matching effective_title, don't duplicate
        first_line = body.splitlines()[0] if body else ""
        if not first_line.startswith("# "):
            sections.append(f"# {effective_title}\n\n{body}")
        else:
            sections.append(body)
    else:
        sections.append(f"# {effective_title}\n")
        role_names = {
            "user": "用户",
            "assistant": "AI 助手",
            "system": "系统",
        }
        for i, msg in enumerate(messages, 1):
            role_label = role_names.get(msg.role, msg.role or "分享内容")
            name_part = f" ({msg.author_name})" if msg.author_name else ""
            sections.append(f"## 消息 {i} · {role_label}{name_part}\n\n{msg.text.strip()}")

    combined = "\n\n---\n\n".join(sections)
    localized = localize_images(combined, images_dir, report)

    safe_title_for_yaml = effective_title.replace('"', '\\"')
    front_matter = f"---\ntitle: \"{safe_title_for_yaml}\"\n---\n\n"
    full_text = front_matter + localized

    md_filename = f"{sanitize_filename(effective_title)}.md"
    md_path = target_dir / md_filename
    md_path.write_text(full_text, encoding="utf-8")

    doc = Document(
        path=md_path,
        rel=md_filename,
        text=localized,
        metadata={"title": effective_title},
        title=effective_title,
    )

    return doc, md_path
