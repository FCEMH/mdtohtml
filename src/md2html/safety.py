"""Raw user HTML is displayed as text; converted fragments use a small allowlist.
KaTeX-generated markup is inserted only AFTER this sanitizer (trusted renderer).
"""

import re
from html import escape

import bleach

from .pandoc_bridge import walk

TAGS = set(bleach.sanitizer.ALLOWED_TAGS) | {
    "p",
    "div",
    "span",
    "section",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "pre",
    "code",
    "img",
    "figure",
    "figcaption",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
    "caption",
    "colgroup",
    "col",
    "hr",
    "br",
    "sup",
    "sub",
    "del",
    "s",
    "dl",
    "dt",
    "dd",
    "input",
    "label",
    "blockquote",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "mark",
}


def prepare(ast, report, source):
    for node in walk(ast["blocks"]):
        t, c = node["t"], node.get("c")
        if t in ("RawInline", "RawBlock"):
            report.add(
                "raw_html_disabled",
                "原始 HTML/TeX 已作为文本保留，不执行",
                source,
                severity="info",
            )
            node["c"] = ["html", escape(c[1])]
        elif t in ("Div", "Span", "CodeBlock", "Code", "Link", "Image"):
            # Headers are separately rewritten by anchors.assign.
            attr = c[0]
            attr[0], attr[2] = "", []
            attr[1] = [x for x in attr[1] if re.fullmatch(r"[\w-]{1,60}", x)]


def sanitize(fragment, doc_id):
    def allowed(tag, name, value):
        if name == "id":
            return value.startswith(doc_id)
        if name in ("class", "title", "alt", "role"):
            return True
        if tag == "a" and name == "href":
            return value.startswith(("#", "https:", "http:", "mailto:"))
        if tag == "img" and name == "src":
            return value.startswith("data:image/")
        return name in {
            "width",
            "height",
            "colspan",
            "rowspan",
            "start",
            "type",
            "checked",
            "disabled",
        }

    # Pandoc's generated code/footnote IDs are local to each document.
    fragment = re.sub(
        r'\bid="([^"]+)"',
        lambda m: f'id="{m[1] if m[1].startswith(doc_id) else doc_id + "--" + m[1]}"',
        fragment,
    )

    def local_href(m):
        target = (
            doc_id + "--" + m[1]
            if re.fullmatch(r"(?:cb\d+(?:-\d+)?|fn\d+|fnref\d+)", m[1])
            else m[1]
        )
        return 'href="#' + target + '"'

    fragment = re.sub(r'\bhref="#([^"\s]+)"', local_href, fragment)
    return bleach.clean(
        fragment,
        tags=TAGS,
        attributes=allowed,
        protocols={"http", "https", "mailto", "data"},
        strip=True,
    )
