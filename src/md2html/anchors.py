"""Namespaced anchors, including harmless Sphinx/HTML anchor declarations."""

import hashlib
from html.parser import HTMLParser
import re
import unicodedata

from .pandoc_bridge import plain, walk


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^\w\-]+", "-", text, flags=re.UNICODE).strip("-") or "section"


def key(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


class AnchorDeclaration(HTMLParser):
    """Accept only a/name/id declarations, never raw HTML execution."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.openings = []
        self.closes = 0
        self.valid = True

    def handle_starttag(self, tag, attrs):
        if tag != "a" or any(k not in {"id", "name", "class"} for k, _ in attrs):
            self.valid = False
            return
        aliases = [v for k, v in attrs if k in {"id", "name"} and v]
        if not aliases or any(
            any(ord(c) < 32 for c in v) or len(v) > 1024 for v in aliases
        ):
            self.valid = False
            return
        self.openings.append(aliases)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.closes += 1

    def handle_endtag(self, tag):
        if tag != "a":
            self.valid = False
        self.closes += 1

    def handle_data(self, text):
        if text.strip():
            self.valid = False

    def handle_comment(self, text):
        self.valid = False

    def handle_decl(self, text):
        self.valid = False


def collect_explicit(ast):
    """Return node/alias pairs BEFORE safety strips all source attributes.

    Raw declarations become empty, program-generated Span/Div nodes. All other
    raw HTML remains untouched for the existing text-escaping safety policy.
    """
    declarations = []
    pending = 0
    for node in list(walk(ast["blocks"])):
        t, c = node["t"], node.get("c")
        if t in {"RawInline", "RawBlock"} and c[0] == "html":
            parser = AnchorDeclaration()
            parser.feed(c[1])
            parser.close()
            if not parser.valid or not (parser.openings or parser.closes):
                pending = 0
                continue
            if not parser.openings and (not pending or parser.closes > pending):
                continue
            pending = max(0, pending + len(parser.openings) - parser.closes)
            if not parser.openings:
                node.update(t="Str", c="") if t == "RawInline" else node.update(
                    t="Div", c=[["", [], []], []]
                )
                continue
            children = []
            for aliases in parser.openings:
                child = {"t": "Span", "c": [[aliases[0], [], []], []]}
                children.append(child)
                declarations.append((child, aliases))
            if t == "RawInline":
                node.update(t="Span", c=[["", [], []], children])
            else:
                node.update(t="Div", c=[["", [], []], [{"t": "Plain", "c": children}]])
        elif (
            t
            in {"Div", "Span", "CodeBlock", "Code", "Link", "Image", "Table", "Figure"}
            and c[0][0]
        ):
            declarations.append((node, [c[0][0]]))
    return declarations


def allocate(doc, stem: str) -> str:
    base = f"{doc.id}--{slug(stem)}"
    candidate, number = base, 1
    while candidate in doc.anchor_ids:
        number += 1
        candidate = f"{base}-{number}"
    doc.anchor_ids.add(candidate)
    return candidate


def aliases(doc, names, anchor):
    for name in names:
        if name:
            doc.anchors.setdefault(key(name), anchor)


def assign(doc, explicit=()):
    doc.id = f"doc-{slug(doc.rel[:-3])[:48]}-{hashlib.sha256(doc.rel.encode()).hexdigest()[:10]}"
    doc.anchor_ids = set()
    nodes = list(walk(doc.ast["blocks"]))
    first_h1 = next((n for n in nodes if n["t"] == "Header" and n["c"][0] == 1), None)
    doc.title = doc.metadata.get("title") or (
        plain(first_h1["c"][2]) if first_h1 else doc.path.stem
    )
    explicit = {id(node): names for node, names in explicit}
    for node in nodes:
        if node["t"] == "Header":
            level, attr, inlines = node["c"]
            label = plain(inlines)
            anchor = allocate(doc, attr[0] or label)
            aliases(
                doc,
                [label, slug(label), attr[0], anchor.removeprefix(doc.id + "--")],
                anchor,
            )
            node["c"][0] = min(6, level + 1)
            node["c"][1] = [anchor, [], []]
            doc.headings.append({"id": anchor, "title": label, "level": level})
        elif id(node) in explicit:
            names = explicit[id(node)]
            anchor = allocate(doc, names[0])
            node["c"][0][0] = anchor
            aliases(doc, [*names, *(slug(n) for n in names)], anchor)
