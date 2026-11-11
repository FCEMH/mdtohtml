from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path

from ..models import BuildError, Report
from .fetch import fetch_url
from .models import ChatGPTShareSource, PreparedInput
from .normalize import messages_to_markdown
from .page_data import parse_chatgpt_html

CHATGPT_URL_PATTERN = re.compile(
    r"^https://(chatgpt\.com|chat\.openai\.com)/(s/t_[a-zA-Z0-9_-]+|s/[a-zA-Z0-9_-]+|share/[a-zA-Z0-9_-]+)(?:[?#].*)?$"
)


def validate_chatgpt_url(url: str) -> str:
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    if not CHATGPT_URL_PATTERN.match(url):
        raise BuildError(
            "无效的 ChatGPT 分享链接。当前支持 https://chatgpt.com/s/... 或 https://chatgpt.com/share/...",
            2,
        )
    return url


def inspect_chatgpt_source(source: ChatGPTShareSource) -> dict:
    """Fetch ChatGPT share page and return metadata without writing files."""
    valid_url = validate_chatgpt_url(source.url)
    raw_data, _ = fetch_url(
        valid_url,
        allowed_hosts=("chatgpt.com", "chat.openai.com"),
    )
    html = raw_data.decode("utf-8", errors="replace")
    messages, title = parse_chatgpt_html(html)

    assistant_count = sum(1 for m in messages if m.role == "assistant")
    user_count = sum(1 for m in messages if m.role == "user")
    total_chars = sum(len(m.text) for m in messages)

    return {
        "type": "chatgpt",
        "url": valid_url,
        "title": title or "ChatGPT 分享内容",
        "message_count": len(messages),
        "assistant_count": assistant_count,
        "user_count": user_count,
        "total_chars": total_chars,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "author_name": m.author_name,
                "snippet": m.text[:120].strip(),
                "chars": len(m.text),
                "text": m.text,
            }
            for m in messages
        ],
    }


def prepare_chatgpt_source(
    source: ChatGPTShareSource,
    report: Report | None = None,
) -> PreparedInput:
    """Fetch ChatGPT share page, extract messages, and generate temporary markdown input."""
    if report is None:
        report = Report()

    if source.messages is not None:
        messages = source.messages
        title = source.title or "ChatGPT 分享内容"
        valid_url = source.url
    else:
        valid_url = validate_chatgpt_url(source.url)
        raw_data, _ = fetch_url(
            valid_url,
            allowed_hosts=("chatgpt.com", "chat.openai.com"),
        )
        html = raw_data.decode("utf-8", errors="replace")
        messages, title = parse_chatgpt_html(html)

    if not messages:
        raise BuildError("分享内容中未找到任何文本消息", 2)

    temp_dir = Path(tempfile.mkdtemp(prefix="md2html_chatgpt_"))
    doc, md_path = messages_to_markdown(messages, title, temp_dir, report)

    fingerprint = hashlib.sha256(
        f"{valid_url}_{len(messages)}_{sum(len(m.text) for m in messages)}".encode()
    ).hexdigest()

    origin = {
        "type": "chatgpt",
        "url": valid_url,
        "title": title,
        "message_count": len(messages),
        "temp_markdown": str(md_path),
    }

    report.stats.update(
        documents=1,
        directories=1,
        input_markdown_bytes=md_path.stat().st_size,
    )

    return PreparedInput(
        root=temp_dir,
        documents=[doc],
        origin=origin,
        source_fingerprint=fingerprint,
        temp_dir=temp_dir,
    )
