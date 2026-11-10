from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

from .models import BuildError


def executable() -> str:
    explicit = os.environ.get("MD2HTML_PANDOC")
    if explicit:
        return explicit
    try:
        import pypandoc

        bundled = Path(pypandoc.__file__).parent / "files" / "pandoc"
        if bundled.is_file():
            return str(bundled)
    except ImportError:
        pass
    return shutil.which("pandoc") or "pandoc"


def run(args: list[str], text: str = "") -> str:
    try:
        result = subprocess.run(
            [executable(), *args],
            input=text,
            capture_output=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
    except FileNotFoundError as e:
        raise BuildError(
            "缺少 Pandoc；安装 pip install '.[pandoc]' 或设置 MD2HTML_PANDOC", 3
        ) from e
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BuildError(f"Pandoc 启动失败: {e}", 4) from e
    if result.returncode:
        raise BuildError(f"Pandoc 转换失败: {result.stderr.strip()}", 4)
    return result.stdout


def version() -> str:
    out = run(["--version"]).splitlines()[0]
    match = re.search(r"\b(\d+)\.(\d+)", out)
    if not match or int(match[1]) != 3:
        raise BuildError(
            f"Pandoc 版本不兼容: {out}；要求 >=3.1,<4；pip install '.[pandoc]'", 3
        )
    if int(match[2]) < 1:
        raise BuildError("Pandoc 版本不兼容；要求 >=3.1,<4", 3)
    return out


def parse(text: str) -> dict:
    # A plaintext bracketed Markdown label [[label]](target) is NOT a WikiLink.
    # Protect only its label (never its destination or surrounding delimiters).
    # Code/math/raw HTML keep their lexical delimiters, and are restored below.
    # Pandoc still parses the complete link, including balanced URL parentheses.
    labels = {}
    prefix = "MD2HTMLSTANDARDLABEL" + hashlib.sha256(text.encode()).hexdigest().upper()
    while prefix in text:
        prefix += "X"

    def protect(match):
        token = prefix + str(len(labels)) + "END"
        labels[token] = "[" + match[1] + "]"
        return "[" + token + "]"

    text = re.sub(r"\[\[([\w .:/&+-]+)\]\](?=\()", protect, text)
    try:
        ast = json.loads(
            run(
                [
                    "-f",
                    "markdown+tex_math_single_backslash+wikilinks_title_after_pipe",
                    "-t",
                    "json",
                ],
                text,
            )
        )
    except ValueError as e:
        raise BuildError("Pandoc 输出无效 JSON", 4) from e
    if labels:

        def restore(value):
            if isinstance(value, str):
                for token, label in labels.items():
                    value = value.replace(token, label)
                return value
            if isinstance(value, list):
                return [restore(v) for v in value]
            if isinstance(value, dict):
                return {k: restore(v) for k, v in value.items()}
            return value

        ast = restore(ast)
    api = ast.get("pandoc-api-version", [])
    if len(api) < 2 or api[0] != 1 or not 23 <= api[1] <= 24:
        raise BuildError(f"未验证的 Pandoc AST API: {api}（支持 1.23–1.24）", 3)
    return ast


def render(ast: dict, highlight: bool = True) -> str:
    # Pandoc 3.1–3.6 use the legacy spelling, while newer versions keep it too.
    options = ["--highlight-style=pygments"] if highlight else ["--no-highlight"]
    return run(
        ["-f", "json", "-t", "html5", *options], json.dumps(ast, ensure_ascii=False)
    )


def walk(value):
    if isinstance(value, dict):
        if "t" in value:
            yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def plain(value) -> str:
    if isinstance(value, list):
        return "".join(plain(v) for v in value)
    if not isinstance(value, dict):
        return ""
    t, c = value.get("t"), value.get("c")
    if t == "Str":
        return c
    if t in ("Space", "SoftBreak", "LineBreak"):
        return " "
    if t in ("Code", "Math"):
        return c[1]
    if t in ("RawInline", "RawBlock"):
        return ""
    if t == "CodeBlock":
        return c[1]
    if t in ("Link", "Image"):
        return plain(c[1])
    return plain(c)
