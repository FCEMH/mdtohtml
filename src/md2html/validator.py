import re
from html.parser import HTMLParser

from .models import BuildError


class OfflineValidator(HTMLParser):
    def __init__(self):
        super().__init__()
        self.errors, self.ids, self.refs = [], [], []
        self.in_style = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        self.in_style = tag == "style"
        if any(k.lower().startswith("on") for k in attrs):
            self.errors.append("event handler attribute")
        if "srcset" in attrs:
            self.errors.append("srcset dependency")
        for name in ("src", "poster", "data"):
            if name in attrs and tag in {
                "script",
                "img",
                "iframe",
                "audio",
                "video",
                "source",
                "track",
                "object",
                "embed",
                "input",
            }:
                if not attrs[name].startswith("data:"):
                    self.errors.append(f"{tag} {name}: {attrs[name]}")
        if tag == "link" and attrs.get("rel") in (
            "stylesheet",
            "preload",
            "prefetch",
            "modulepreload",
            "icon",
        ):
            if not attrs.get("href", "").startswith("data:"):
                self.errors.append("external link resource")
        if tag == "a":
            href = attrs.get("href", "")
            if href.startswith("#"):
                self.refs.append(href[1:])
            elif attrs.get("download") and re.fullmatch(
                r"data:application/json;base64,[A-Za-z0-9+/]*={0,2}", href
            ):
                pass  # Only renderer-generated, explicitly downloadable local JSON.
            elif href and not href.startswith(("http:", "https:", "mailto:")):
                self.errors.append("non-inline document link: " + href)
        if "style" in attrs:
            self.check_css(attrs["style"])

    def handle_endtag(self, tag):
        if tag == "style":
            self.in_style = False

    def handle_data(self, data):
        if self.in_style:
            self.check_css(data)

    def check_css(self, css):
        if re.search(r"@import\b", css, re.IGNORECASE):
            self.errors.append("CSS @import")
        for target in re.findall(r"url\(\s*[\'\"]?([^\)\'\"]+)", css, re.IGNORECASE):
            if not target.startswith(("data:", "#")):
                self.errors.append("CSS resource: " + target)


def validate(html):
    parser = OfflineValidator()
    parser.feed(html)
    if len(parser.ids) != len(set(parser.ids)):
        parser.errors.append("duplicate DOM IDs")
    known = set(parser.ids)
    parser.errors.extend(
        "missing anchor: " + r for r in parser.refs if r and r not in known
    )
    if parser.errors:
        raise BuildError(
            "HTML 完整性/离线验证失败: " + "; ".join(parser.errors[:12]), 4
        )
    return {
        "offline_verified": True,
        "dom_ids": len(known),
        "anchor_links": len(parser.refs),
    }
