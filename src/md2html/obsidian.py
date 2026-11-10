"""Obsidian AST extensions. Pandoc handles code/math lexical isolation."""

import re

from .pandoc_bridge import plain, walk


def callouts(ast, report, source):
    for node in list(walk(ast["blocks"])):
        if node["t"] != "BlockQuote" or not node["c"]:
            continue
        first = node["c"][0]
        if first["t"] not in ("Para", "Plain") or not first["c"]:
            continue
        inline = first["c"][0]
        if inline["t"] != "Str":
            continue
        match = re.fullmatch(r"\[!([\w-]+)\]([+-]?)", inline["c"])
        if not match:
            continue
        kind = match[1].casefold()
        if kind not in ("note", "tip", "warning"):
            report.add(
                "unsupported_callout", f"Callout 类型 {kind} 降级为 note", source
            )
            kind = "note"
        inline["c"] = {"note": "笔记", "tip": "提示", "warning": "注意"}[kind] + "："
        node.update(t="Div", c=[["", ["callout", "callout-" + kind], []], node["c"]])


def image_size(node):
    label = plain(node["c"][1])
    match = re.fullmatch(r"([1-9]\d{0,4})(?:x([1-9]\d{0,4}))?", label)
    if not match:
        return
    # Width/height form a maximum bounding box; CSS keeps the aspect ratio.
    attrs = [["width", match[1]]]
    if match[2]:
        attrs.append(["height", match[2]])
    node["c"][0][2] = attrs
    target = node["c"][2][0].split("/")[-1]
    node["c"][1] = [{"t": "Str", "c": target}]
