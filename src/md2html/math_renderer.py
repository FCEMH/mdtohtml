from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
from functools import lru_cache
from html import escape
from pathlib import Path

from .models import BuildError
from .anchors import allocate, aliases, key
from .pandoc_bridge import walk

PACKAGE = Path(__file__).parent
VENDOR = PACKAGE / "vendor"


def node_executable():
    return os.environ.get("MD2HTML_NODE") or shutil.which("node") or "node"


def node_call(data=None):
    args = [node_executable(), str(PACKAGE / "node" / "render_math.mjs")]
    if data is None:
        args.append("--probe")
    try:
        result = subprocess.run(
            args,
            input=json.dumps(data),
            capture_output=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise BuildError(
            f"Node/KaTeX 不可用: {e}；安装 Node >=20 并在项目根目录执行 npm ci", 3
        ) from e
    if result.returncode:
        raise BuildError(
            f"本地 KaTeX 失败: {result.stderr.strip()}；执行 npm ci",
            3 if data is None else 4,
        )
    try:
        return json.loads(result.stdout)
    except ValueError as e:
        raise BuildError("KaTeX 输出了无效 JSON", 4) from e


def probe():
    result = node_call()
    if int(result["node"].split(".")[0]) < 20:
        raise BuildError(f"Node {result['node']} 不兼容，要求 >=20", 3)
    fonts = list((VENDOR / "fonts").glob("*.woff2"))
    if not (VENDOR / "katex.min.css").is_file() or len(fonts) < 20:
        raise BuildError("KaTeX CSS/字体包不完整；在项目根目录执行 npm ci", 3)
    return {**result, "fonts": len(fonts)}


@lru_cache(maxsize=1)
def css():
    text = (VENDOR / "katex.min.css").read_text(encoding="utf-8")

    def source(match):
        woff = re.search(r"url\(([^)]+\.woff2)\)", match[0])
        if not woff:
            raise BuildError("KaTeX CSS 中找不到 WOFF2 字体", 3)
        path = VENDOR / woff[1].strip("\"'")
        if not path.is_file() or not path.resolve().is_relative_to(VENDOR.resolve()):
            raise BuildError("KaTeX 字体路径无效", 3)
        uri = base64.b64encode(path.read_bytes()).decode()
        return f'src:url(data:font/woff2;base64,{uri}) format("woff2"){match[2]}'

    return re.sub(r"src:([^;}]+)([;}])", source, text)


DISPLAY_ENVIRONMENT = re.compile(
    r"\s*\\begin\{(equation\*?|align\*?|alignat\*?|gather\*?)\}"
    r"[\s\S]*\\end\{\1\}\s*"
)


def extract_labels(tex):
    r"""Strip genuine label controls from renderer input, not verbatim/comments.

    This does NOT edit source text, implement TeX macros, or promise eqref/numbering.
    Escaped backslashes and \verb payloads retain their exact original spelling.
    """
    output, labels, i = [], [], 0
    while i < len(tex):
        if tex[i] == "%":
            end = tex.find("\n", i)
            end = len(tex) if end < 0 else end
            output.append(tex[i:end])
            i = end
        elif tex[i] == "\\":
            command = re.match(r"\\([A-Za-z]+|.)", tex[i:])
            if not command:
                output.append(tex[i])
                i += 1
                continue
            name = command[1]
            end = i + len(command[0])
            if name == "verb":
                delimiter_pos = end + (end < len(tex) and tex[end] == "*")
                if delimiter_pos < len(tex) and not tex[delimiter_pos].isspace():
                    closing = tex.find(tex[delimiter_pos], delimiter_pos + 1)
                    if closing >= 0:
                        output.append(tex[i : closing + 1])
                        i = closing + 1
                        continue
            if name == "label":
                argument = re.match(r"\s*\{([^{}]+)\}", tex[end:])
                if argument:
                    labels.append(argument[1].strip())
                    i = end + len(argument[0])
                    continue
            output.append(tex[i:end])
            i = end
        else:
            output.append(tex[i])
            i += 1
    return "".join(output), labels


def render_math(docs, report):
    probe()
    items, nodes, originals, label_markup, replacements = [], [], [], [], {}
    normalized_count, label_count = 0, 0
    for doc in docs:
        seen_labels = set()
        for node in list(walk(doc.ast["blocks"])):
            if node["t"] != "Math":
                continue
            original = node["c"][1]
            tex, labels = extract_labels(original)
            display = node["c"][0]["t"] == "DisplayMath"
            if not display and DISPLAY_ENVIRONMENT.fullmatch(tex):
                display = True
                normalized_count += 1
                report.add(
                    "math_display_normalized",
                    "外层展示公式环境按展示模式渲染（源文件未修改）",
                    doc.rel,
                    severity="info",
                )
            markup = ""
            if labels:
                label_count += len(labels)
                for label in labels:
                    if not label or key(label) in seen_labels:
                        report.add(
                            "duplicate_math_label",
                            f"公式标签为空或重复: {label}",
                            doc.rel,
                        )
                    seen_labels.add(key(label))
                existing = next(
                    (
                        doc.anchors[key(label)]
                        for label in labels
                        if key(label) in doc.anchors
                    ),
                    None,
                )
                anchor = existing or allocate(doc, "equation-" + labels[0])
                aliases(doc, labels, anchor)
                if not existing:
                    markup = (
                        '<span class="equation-anchor" id="'
                        + escape(anchor, quote=True)
                        + '"></span>'
                    )
                report.add(
                    "math_label_extracted",
                    "公式标签已保留为安全锚点: " + ", ".join(labels),
                    doc.rel,
                    severity="info",
                )
            items.append({"tex": tex, "display": display})
            nodes.append((doc, node))
            originals.append(original)
            label_markup.append(markup)
    results = node_call(items) if items else []
    if not isinstance(results, list) or len(results) != len(items):
        raise BuildError("KaTeX 批量响应数量不匹配", 4)
    for i, ((doc, node), original, result, label, item) in enumerate(
        zip(nodes, originals, results, label_markup, items)
    ):
        token = (
            "MD2HTMLMATH"
            + hashlib.sha256((doc.rel + str(i) + original).encode()).hexdigest().upper()
        )
        while any(token in d.text for d in docs):
            token += "X"
        if "error" in result:
            report.add(
                "math_error",
                f"LaTeX: {original}\n{result['error']}",
                doc.rel,
                suggestion="修正 LaTeX 或改用 KaTeX 支持的宏",
            )
            markup = (
                '<span class="math-error" role="note">公式未渲染：<code>'
                + escape(original)
                + "</code></span>"
            )
        else:
            markup = result["html"]
            if not item["display"]:
                markup = '<span class="math-inline">' + markup + "</span>"
        replacements[token] = label + markup
        node.update(t="Str", c=token)
    report.stats.update(
        math_expressions=len(items),
        math_display_normalized=normalized_count,
        math_labels=label_count,
    )
    return replacements
