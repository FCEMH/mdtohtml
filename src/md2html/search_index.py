import json
from functools import lru_cache

from .pandoc_bridge import plain, walk
from .anchors import allocate


def index_documents(docs):
    entries = []
    for doc in docs:
        entries.append(
            {"id": doc.id, "chapter": doc.title, "text": doc.title, "source": doc.rel}
        )
        number = 0
        for node in list(walk(doc.ast["blocks"])):
            if node["t"] not in ("Para", "Plain", "CodeBlock", "Header"):
                continue
            text = plain(node).strip()
            if not text:
                continue
            number += 1
            if node["t"] == "Header":
                anchor = node["c"][1][0]
            elif node["t"] == "CodeBlock":
                anchor = node["c"][0][0] or allocate(doc, f"p-{number}")
                node["c"][0][0] = anchor
            else:
                anchor = allocate(doc, f"p-{number}")
                node["c"].insert(0, {"t": "Span", "c": [[anchor, [], []], []]})
            entries.append(
                {"id": anchor, "chapter": doc.title, "text": text, "source": doc.rel}
            )
    return entries


@lru_cache(maxsize=1)
def casefold_map():
    return {
        chr(i): chr(i).casefold()
        for i in range(0x110000)
        if chr(i).casefold() != chr(i).lower()
    }


def safe_json(value):
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
