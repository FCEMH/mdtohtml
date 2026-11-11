from __future__ import annotations

import json
import re
from typing import Any

from ..models import BuildError
from .models import ChatMessage


def extract_title_from_markdown(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def extract_title_from_html(html: str) -> str:
    og_m = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\'](.*?)["\']', html, re.IGNORECASE)
    if og_m:
        val = og_m.group(1).strip()
        if val and "ChatGPT" not in val and "聊天" not in val:
            return val
    title_m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
    if title_m:
        val = title_m.group(1).strip()
        cleaned = re.sub(r"(\s*-\s*ChatGPT|\s*\|\s*ChatGPT).*", "", val, flags=re.IGNORECASE).strip()
        if cleaned and cleaned != "Shared Content":
            return cleaned
    return ""


def extract_from_turbo_stream(html: str) -> tuple[list[ChatMessage], str]:
    """Extract messages and conversation title from React Router v7 / Remix turbo-stream payload."""
    start_str = "streamController.enqueue("
    idx = html.find(start_str)
    if idx == -1:
        return [], ""

    try:
        decoder = json.JSONDecoder()
        decoded_str, _ = decoder.raw_decode(html, idx + len(start_str))
        parsed = json.loads(decoded_str)
    except (ValueError, json.JSONDecodeError) as e:
        raise BuildError(f"页面数据解析失败 (turbo-stream): {e}", 2) from e

    if not isinstance(parsed, list):
        return [], ""

    def get_val(v: Any) -> Any:
        if isinstance(v, int):
            if 0 <= v < len(parsed):
                return parsed[v]
            return None
        return v

    def get_dict_props(d: Any) -> dict[str, Any]:
        if not isinstance(d, dict):
            return {}
        res: dict[str, Any] = {}
        for k, v in d.items():
            name = parsed[int(k[1:])] if k.startswith("_") and k[1:].isdigit() and int(k[1:]) < len(parsed) else k
            res[str(name)] = v
        return res

    def parse_msg_dict(item_or_node: dict) -> ChatMessage | None:
        raw = get_dict_props(item_or_node)
        msg_ref = raw.get("message")
        if msg_ref is not None:
            msg_val = get_val(msg_ref)
            if isinstance(msg_val, dict):
                props = get_dict_props(msg_val)
            else:
                return None
        elif "author" in raw and "content" in raw:
            props = raw
        else:
            return None

        author_val = get_val(props.get("author"))
        author_props = get_dict_props(author_val) if isinstance(author_val, dict) else {}
        role = str(get_val(author_props.get("role")) or "unknown")
        author_name = get_val(author_props.get("name"))

        meta_val = get_val(props.get("metadata"))
        meta_props = get_dict_props(meta_val) if isinstance(meta_val, dict) else {}
        is_hidden = bool(get_val(meta_props.get("is_visually_hidden_from_conversation")))
        is_user_sys = bool(get_val(meta_props.get("is_user_system_message")))
        is_redacted = bool(get_val(meta_props.get("is_redacted")))

        content_val = get_val(props.get("content"))
        content_props = get_dict_props(content_val) if isinstance(content_val, dict) else {}
        content_type = str(get_val(content_props.get("content_type")) or "")

        parts_val = get_val(content_props.get("parts"))
        text_parts = []
        if isinstance(parts_val, list):
            for p in parts_val:
                pv = get_val(p)
                if isinstance(pv, str):
                    text_parts.append(pv)
        elif isinstance(parts_val, str):
            text_parts.append(parts_val)

        text = "".join(text_parts).strip()
        if not text:
            return None
        if text == "The output of this plugin was redacted.":
            return None
        if is_hidden or is_user_sys or is_redacted:
            return None
        if role not in ("user", "assistant"):
            return None
        if content_type in ("thoughts", "reasoning_recap", "model_editable_context"):
            return None

        msg_id = str(get_val(props.get("id")) or f"msg-{id(item_or_node)}")
        create_time = get_val(props.get("create_time"))
        try:
            create_time_f = float(create_time) if create_time is not None else None
        except (ValueError, TypeError):
            create_time_f = None

        return ChatMessage(
            id=msg_id,
            role=role,
            text=text,
            create_time=create_time_f,
            author_name=str(author_name) if author_name else None,
        )

    # 1. Check if there is linear_conversation (active thread in topological order)
    ordered_nodes: list[dict] = []
    conversation_title = ""

    for item in parsed:
        if isinstance(item, dict):
            props = get_dict_props(item)
            if "linear_conversation" in props:
                lc = get_val(props["linear_conversation"])
                if isinstance(lc, list) and lc:
                    ordered_nodes = [get_val(x) for x in lc if isinstance(get_val(x), dict)]
                    t = get_val(props.get("title"))
                    if isinstance(t, str) and t.strip():
                        conversation_title = t.strip()
                    break
            elif props.get("kind") == "message_slice" or props.get("source_attachment_type") == "message_slice":
                msgs_idx = props.get("messages")
                msgs_list = get_val(msgs_idx)
                if isinstance(msgs_list, list):
                    ordered_nodes = [get_val(x) for x in msgs_list if isinstance(get_val(x), dict)]
                    break

    messages: list[ChatMessage] = []
    if ordered_nodes:
        for node in ordered_nodes:
            m = parse_msg_dict(node)
            if m:
                messages.append(m)
    else:
        # Fallback: scan parsed items for messages, deduplicate, and sort by create_time
        seen_ids = set()
        raw_msgs: list[ChatMessage] = []
        for item in parsed:
            if isinstance(item, dict):
                m = parse_msg_dict(item)
                if m and m.id not in seen_ids:
                    seen_ids.add(m.id)
                    raw_msgs.append(m)
        if raw_msgs:
            if all(m.create_time is not None for m in raw_msgs):
                raw_msgs.sort(key=lambda x: x.create_time or 0.0)
            messages = raw_msgs

    title = conversation_title
    if not title and messages:
        title = extract_title_from_markdown(messages[0].text)
    if not title:
        title = extract_title_from_html(html)

    return messages, title


def extract_from_next_data(html: str) -> tuple[list[ChatMessage], str]:
    """Extract messages and conversation title from Next.js __NEXT_DATA__ JSON tag."""
    m = re.search(r'<script\s+id=["\']__NEXT_DATA__["\']\s+type=["\']application/json["\']>(.*?)</script>', html, re.DOTALL)
    if not m:
        return [], ""

    try:
        data = json.loads(m.group(1))
    except (ValueError, json.JSONDecodeError) as e:
        raise BuildError(f"页面数据解析失败 (__NEXT_DATA__): {e}", 2) from e

    props = data.get("props", {}).get("pageProps", {})
    server_res = props.get("serverResponse", {}).get("data", {}) or props.get("sharedConversation", {})
    linear_conv = server_res.get("linear_conversation", [])
    title = server_res.get("title", "")

    messages: list[ChatMessage] = []
    if isinstance(linear_conv, list):
        for item in linear_conv:
            if not isinstance(item, dict):
                continue
            msg_obj = item.get("message") if isinstance(item.get("message"), dict) else item
            author = msg_obj.get("author", {})
            role = str(author.get("role") or "unknown")
            if role not in ("user", "assistant"):
                continue
            meta = msg_obj.get("metadata", {})
            if meta.get("is_visually_hidden_from_conversation") or meta.get("is_user_system_message"):
                continue
            content = msg_obj.get("content", {})
            content_type = str(content.get("content_type") or "")
            if content_type in ("thoughts", "reasoning_recap", "model_editable_context"):
                continue
            parts = content.get("parts", [])
            text = "".join(p for p in parts if isinstance(p, str)).strip()
            if text and text != "The output of this plugin was redacted.":
                messages.append(
                    ChatMessage(
                        id=str(msg_obj.get("id", f"msg-{len(messages)}")),
                        role=role,
                        text=text,
                        create_time=msg_obj.get("create_time"),
                        author_name=author.get("name"),
                    )
                )

    if not title and messages:
        title = extract_title_from_markdown(messages[0].text)
    if not title:
        title = extract_title_from_html(html)

    return messages, title


def extract_from_octane(html: str) -> tuple[list[ChatMessage], str]:
    """Extract messages and title from OpenAI Octane architecture scripts."""
    scripts = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL)
    best_messages: list[ChatMessage] = []
    best_title = ""

    for s in scripts:
        s = s.strip()
        if not s.startswith("{") or not s.endswith("}"):
            continue
        try:
            data = json.loads(s)
            if not isinstance(data, dict):
                continue

            # Check conversation / conversationState
            conv = data.get("conversation") or data.get("conversationState")
            if isinstance(conv, dict) and "messages" in conv:
                raw_msgs = conv.get("messages")
                if isinstance(raw_msgs, list) and raw_msgs:
                    messages: list[ChatMessage] = []
                    for m in raw_msgs:
                        if not isinstance(m, dict):
                            continue
                        role = m.get("role", "assistant")
                        if role not in ("user", "assistant"):
                            continue
                        msg_id = m.get("id", f"msg-{len(messages)}")
                        content = m.get("content") or m.get("text")
                        if not content and "source" in m:
                            src = m.get("source", {})
                            content = (
                                src.get("content")
                                or src.get("dil", {}).get("fallbackMarkdown")
                                or src.get("markdown")
                            )

                        if isinstance(content, str) and content.strip():
                            messages.append(ChatMessage(id=msg_id, role=role, text=content.strip()))

                    title = conv.get("title") or ""
                    if len(messages) > len(best_messages) or (len(messages) == len(best_messages) and title and not best_title):
                        best_messages = messages
                        best_title = title

            # Check rows
            if "rows" in data and isinstance(data["rows"], list) and data["rows"]:
                messages = []
                for row in data["rows"]:
                    if not isinstance(row, dict):
                        continue
                    frame = row.get("frame", {})
                    source = row.get("source", {})
                    role = frame.get("role") or row.get("role") or "assistant"
                    if role not in ("user", "assistant"):
                        continue
                    msg_id = row.get("key") or frame.get("id", f"msg-{len(messages)}")
                    content = (
                        frame.get("text")
                        or row.get("text")
                        or source.get("content")
                        or source.get("dil", {}).get("fallbackMarkdown")
                        or source.get("markdown")
                    )
                    if isinstance(content, str) and content.strip():
                        messages.append(ChatMessage(id=msg_id, role=role, text=content.strip()))

                if len(messages) > len(best_messages) or (len(messages) == len(best_messages) and not best_title):
                    best_messages = messages

        except Exception:
            continue

    if not best_title and best_messages:
        best_title = extract_title_from_markdown(best_messages[0].text) or extract_title_from_html(html)

    return best_messages, best_title


def parse_chatgpt_html(html: str) -> tuple[list[ChatMessage], str]:
    """Extract messages and title from ChatGPT share HTML, supporting multiple page formats."""
    # First try turbo-stream (React Router v7 format)
    messages, title = extract_from_turbo_stream(html)
    if messages:
        return messages, title

    # Next try Octane architecture format
    messages, title = extract_from_octane(html)
    if messages:
        return messages, title

    # Next try __NEXT_DATA__ (classic Next.js format)
    messages, title = extract_from_next_data(html)
    if messages:
        return messages, title

    # Check if page was a login / error page
    if "Please turn JavaScript on" in html or "cf-turnstile" in html:
        raise BuildError("页面受人机验证保护或需要启用 JavaScript", 2)
    if "Log in" in html and "Sign up" in html and len(html) < 20000:
        raise BuildError("分享内容需要登录访问", 2)

    raise BuildError("未能从页面中识别出分享正文（可能页面结构发生变动或已撤销分享）", 2)
