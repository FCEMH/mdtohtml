import argparse
from collections import Counter
import sys
from pathlib import Path

import yaml

from . import math_renderer, pandoc_bridge, __version__
from .config import DEFAULTS, load_config
from .html_builder import build
from .models import BuildError, Report
from .output_policy import protect_target
from .report import atomic_write, save_report


class CLIParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(1, f"参数错误: {message}\n")


def parser():
    p = CLIParser(prog="md2html", description="Markdown 文件夹 → 单文件离线教材")
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("input", type=Path)
    init.add_argument("--force", action="store_true")
    sub.add_parser("doctor")
    for name in ("check", "build"):
        cmd = sub.add_parser(name)
        cmd.add_argument("input", type=Path)
        if name == "build":
            cmd.add_argument("-o", "--output", type=Path)
        cmd.add_argument("--config", type=Path)
        cmd.add_argument("--title")
        cmd.add_argument("--theme", choices=["auto", "light", "dark"])
        cmd.add_argument("--toc-depth", type=int)
        cmd.add_argument(
            "--search", action=argparse.BooleanOptionalAction, default=None
        )
        cmd.add_argument("--offline", action="store_true", default=None)
        cmd.add_argument("--strict", action="store_true", default=None)
        cmd.add_argument("--report", type=Path)
        cmd.add_argument("--verbose", action="store_true")
    return p



def main(argv=None):
    args = parser().parse_args(argv)
    report = Report()
    code = 0
    report_path = None
    try:
        if args.command == "doctor":
            print(
                f"Python: {sys.version.split()[0]}\nPandoc 路径: {pandoc_bridge.executable()}"
            )
            risks = []
            try:
                print(pandoc_bridge.version())
            except BuildError as e:
                risks.append(str(e))
            print(f"Node 路径: {math_renderer.node_executable()}")
            try:
                info = math_renderer.probe()
                print(
                    f"Node: {info['node']} / KaTeX: {info['katex']} / 字体: {info['fonts']} WOFF2"
                )
            except BuildError as e:
                risks.append(str(e))
            templates = Path(__file__).parent / "templates"
            intact = all(
                (templates / n).is_file()
                for n in ("reader.html.j2", "reader.css", "reader.js", "print.css")
            )
            print("模板: " + ("完整" if intact else "缺失"))
            if not intact:
                risks.append("模板包不完整；重新安装本 Python 包")
            if risks:
                for risk in risks:
                    print("ERROR: " + risk, file=sys.stderr)
                return 3
            print("构建依赖正常；阅读端不需要 Python、Pandoc 或 Node。")
            return 0
        if args.input.is_symlink():
            raise BuildError("输入根目录不能是符号链接")
        root = args.input.resolve()
        if getattr(args, "report", None):
            report_path = protect_target(args.report, root, ".json")
        if args.command == "init":
            if not root.is_dir():
                raise BuildError(f"输入目录不存在: {root}")
            path = root / "md2html.yml"
            if path.is_symlink() or (path.exists() and not args.force):
                raise BuildError("配置已存在，拒绝覆盖；可使用 --force")
            atomic_write(
                path, yaml.safe_dump(DEFAULTS, allow_unicode=True, sort_keys=False)
            )
            print(f"已创建: {path}")
            return 0
        config = load_config(
            root,
            args.config,
            {
                "book.title": args.title,
                "render.theme": args.theme,
                "render.toc_depth": args.toc_depth,
                "render.search": args.search,
                "render.offline": args.offline,
                "render.strict": args.strict,
            },
        )
        output = None
        if args.command == "build":
            output = protect_target(
                args.output or Path("dist") / f"{root.name}.html", root, ".html"
            )
        _, docs = build(root, config, report, output)
        if args.verbose:
            for doc in docs:
                print(f"[md2html] {doc.rel} -> #{doc.id}")
            print(f"[md2html] {report.stats}")
        print(
            f"[md2html] {len(docs)} 章 / 图片 {report.stats['image_references']} / 唯一图片 {report.stats['unique_images']}"
        )
        print(f"[md2html] {'生成成功: ' + str(output) if output else '检查通过'}")
    except BuildError as e:
        code = e.code
        report.status, report.exit_code = "failed", code
        report.add("fatal", str(e), severity="error")
    except (OSError, ValueError) as e:
        code = 1
        report.status, report.exit_code = "failed", code
        report.add("io_error", str(e), severity="error")
    infos = Counter(i.code for i in report.issues if i.severity == "info")
    if infos and not getattr(args, "verbose", False):
        detail = ", ".join(f"{k}={v}" for k, v in sorted(infos.items()))
        print(
            f"[md2html] INFO 兼容/安全处理 {sum(infos.values())} 条（{detail}）；--verbose 查看明细，--report 保存完整记录",
            file=sys.stderr,
        )
    for issue in report.issues:
        if issue.severity == "info" and not getattr(args, "verbose", False):
            continue
        print(
            f"[md2html] {issue.severity.upper()} {issue.source or '(构建)'}:{issue.line or '位置未知'} [{issue.code}] {issue.message}",
            file=sys.stderr,
        )
    warnings = sum(i.severity == "warning" for i in report.issues)
    errors = sum(i.severity == "error" for i in report.issues)
    print(f"[md2html] 结果: 退出码 {code} / 警告 {warnings} / 错误 {errors}")
    if report_path is not None:
        try:
            save_report(report_path, report)
        except OSError as e:
            print(f"报告写入失败: {e}", file=sys.stderr)
            return 1
    return code
