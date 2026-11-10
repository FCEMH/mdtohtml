from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from . import math_renderer
from . import pandoc_bridge as pandoc
from .anchors import assign, collect_explicit
from .assets import Assets
from .attachments import Attachments
from .models import BuildError
from .obsidian import callouts, image_size
from .report import atomic_write
from .resolver import Resolver
from .safety import prepare, sanitize
from .scanner import scan
from .search_index import casefold_map, index_documents, safe_json
from .validator import validate

TEMPLATES = Path(__file__).parent / "templates"


def navigation(docs, depth=3):
    all_parents = [Path(d.rel).parts[:-1] for d in docs]
    parents_with_subdirs = set()
    for p in all_parents:
        for i in range(len(p)):
            parents_with_subdirs.add(p[:i])

    tree = []
    for doc in docs:
        doc_parent = Path(doc.rel).parts[:-1]
        children = tree
        for folder in doc_parent:
            item = next((n for n in children if n.get("folder") == folder), None)
            if item is None:
                item = {"folder": folder, "title": folder, "children": []}
                children.append(item)
            children = item["children"]

        if doc_parent in parents_with_subdirs:
            heading_children = []
        else:
            heading_children = [
                h
                for h in doc.headings
                if h["level"] <= depth
                and not (h["level"] == 1 and h["title"] == doc.title)
            ]

        children.append(
            {
                "id": doc.id,
                "title": doc.title,
                "children": heading_children,
            }
        )
    return tree


def build(
    root,
    config,
    report,
    output=None,
    *,
    documents=None,
    on_progress=None,
    cancel_token=None,
):
    def check_cancel():
        if cancel_token is not None and getattr(cancel_token, "cancelled", False):
            raise BuildError("构建已取消", 0)

    def progress(stage, current, total, source="", message=""):
        if on_progress:
            on_progress(
                {
                    "stage": stage,
                    "current": current,
                    "total": total,
                    "source": source,
                    "message": message,
                }
            )

    check_cancel()
    pandoc.version()
    if documents is None:
        progress("scan", 0, 1, message="正在扫描目录...")
        docs = scan(root, config, report)
    else:
        docs = documents

    total_docs = len(docs)
    assets = Assets(root, config, report)
    attachments = Attachments(root, assets, report)

    for i, doc in enumerate(docs, 1):
        check_cancel()
        progress("parse", i, total_docs, doc.rel, f"正在解析 Markdown ({i}/{total_docs})")
        doc.ast = pandoc.parse(doc.text)
        for node in pandoc.walk(doc.ast["blocks"]):
            if node["t"] == "CodeBlock" and set(node["c"][0][1]) & {
                "mermaid",
                "dot",
                "graphviz",
                "dataview",
                "dataviewjs",
            }:
                report.add(
                    "unsupported_plugin", "P2 插件/图表保留为代码，不执行", doc.rel
                )
        explicit = collect_explicit(doc.ast)
        report.stats["explicit_anchors"] = report.stats.get(
            "explicit_anchors", 0
        ) + len(explicit)
        prepare(doc.ast, report, doc.rel)
        assign(doc, explicit)
        callouts(doc.ast, report, doc.rel)

    check_cancel()
    progress("search_index", 0, 1, message="构建搜索索引...")
    search_index = index_documents(docs) if config["render"]["search"] else []

    check_cancel()
    progress("math", 0, total_docs, message="正在渲染数学公式...")
    math_replacements = math_renderer.render_math(docs, report)

    check_cancel()
    resolver = Resolver(root, docs, config, report, attachments)
    for i, doc in enumerate(docs, 1):
        check_cancel()
        progress("resolve", i, total_docs, doc.rel, f"解析资源与链接 ({i}/{total_docs})")
        for node in list(pandoc.walk(doc.ast["blocks"])):
            if node["t"] == "Image":
                target = node["c"][2][0]
                wiki = "wikilink" in node["c"][0][1]
                if wiki:
                    image_size(node)
                if wiki and Path(target.split("#")[0]).suffix.lower() in ("", ".md"):
                    report.add(
                        "unsupported_transclusion",
                        f"P2 正文嵌入未实现: {target}",
                        doc.rel,
                    )
                    uri = None
                else:
                    path = resolver.image_path(doc, target, wiki)
                    uri = assets.encode(doc, path) if path else None
                assets.references += 1
                if uri:
                    node["c"][2][0] = uri
                else:
                    node.update(
                        t="Span",
                        c=[
                            [node["c"][0][0], ["unresolved-reference"], []],
                            [{"t": "Str", "c": f"[未打包图片/嵌入: {target}]"}],
                        ],
                    )
            elif node["t"] == "Link":
                target = node["c"][2][0]
                uri = resolver.link(doc, target, "wikilink" in node["c"][0][1])
                if uri:
                    node["c"][2][0] = uri
                else:
                    node.update(
                        t="Span",
                        c=[
                            [node["c"][0][0], ["unresolved-reference"], []],
                            [{"t": "Str", "c": f" [未解析: {target}]"}],
                        ],
                    )
        doc.html = sanitize(
            pandoc.render(doc.ast, config["render"]["code_highlight"]), doc.id
        )
        for token, markup in math_replacements.items():
            doc.html = doc.html.replace(token, markup)

    report.stats.update(
        assets.stats(), **attachments.stats(), internal_links=resolver.links
    )
    if config["render"]["strict"] and any(i.severity != "info" for i in report.issues):
        raise BuildError("严格模式: 内容检查未通过", 2)

    check_cancel()
    progress("assemble", 0, 1, message="组装 HTML 模板...")
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
    html = env.get_template("reader.html.j2").render(
        docs=docs,
        attachments=list(attachments.entries.values()),
        toc=navigation(docs, config["render"]["toc_depth"]),
        config=config,
        index_json=safe_json(
            {
                "entries": search_index,
                "casefold": casefold_map(),
                "lightbox": config["render"]["image_lightbox"],
            }
        ),
        css=(TEMPLATES / "reader.css").read_text() + "\n" + math_renderer.css(),
        print_css=(TEMPLATES / "print.css").read_text(),
        license=(math_renderer.VENDOR / "KATEX-LICENSE.txt").read_text(),
        js=(TEMPLATES / "reader.js").read_text(),
    )
    report.stats["output_bytes"] = len(html.encode())

    check_cancel()
    progress("validate", 0, 1, message="离线完整性校验...")
    report.stats.update(validate(html))
    if report.stats["output_bytes"] > config["limits"]["warn_output_mb"] * 1024**2:
        report.add(
            "large_output",
            f"输出 HTML {report.stats['output_bytes']} bytes，超过体积阈值",
        )

    if output is not None:
        check_cancel()
        progress("save", 0, 1, message="写入输出文件...")
        atomic_write(output, html)

    report.status = "success"
    progress("done", 1, 1, message="完成")
    return html, docs
