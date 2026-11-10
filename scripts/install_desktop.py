"""Generate a Linux desktop entry for this checkout or a chosen GUI executable."""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path


def desktop_value(value: str) -> str:
    if any(char in value for char in ("\n", "\r", "\x00")):
        raise ValueError("桌面入口的路径不能包含换行或空字符")
    return value.replace("\\", "\\\\").replace("\t", "\\t")


def quote_exec(executable: Path) -> str:
    value = str(executable)
    if "=" in value:
        raise ValueError("桌面入口的可执行文件路径不能包含等号")
    value = value.replace("%", "%%")
    quoted = "".join("\\" + char if char in '\\"`$' else char for char in value)
    return desktop_value('"' + quoted + '"')


def default_applications_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME", "")
    base = Path(data_home) if data_home and Path(data_home).is_absolute() else Path.home() / ".local/share"
    return base / "applications"


def install_desktop(
    project_root: Path,
    executable: Path | None = None,
    applications_dir: Path | None = None,
) -> Path:
    project_root = project_root.resolve()
    executable = (executable or project_root / ".venv/bin/md2html-gui").expanduser().absolute()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError(
            f"GUI 启动程序不存在或不可执行：{executable}\n"
            "请先在项目中安装：.venv/bin/python -m pip install -e '.[gui,pandoc]'\n"
            "其他安装环境可用 --executable 指定 md2html-gui 的路径。"
        )

    template = (project_root / "md2html.desktop.in").read_text(encoding="utf-8")
    replacements = {
        # Pass the application path as an argument, including literal % signs.
        "@EXEC@": "env " + quote_exec(executable),
        "@TRY_EXEC@": desktop_value(str(executable)),
        "@PROJECT_ROOT@": desktop_value(str(project_root)),
    }
    for key in replacements:
        if template.count(key) != 1:
            raise ValueError(f"桌面入口模板缺少或重复占位符：{key}")
    # Replace placeholders in one pass so a literal token in a path stays literal.
    content = re.sub(r"@(?:EXEC|TRY_EXEC|PROJECT_ROOT)@", lambda m: replacements[m[0]], template)

    destination = (applications_dir or default_applications_dir()).expanduser().absolute()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "md2html.desktop"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination, prefix=".md2html-", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        temporary.chmod(0o644)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="为当前安装位置生成 MD2HTML Linux 桌面入口")
    parser.add_argument("--executable", type=Path, help="已安装的 md2html-gui 路径；默认使用项目 .venv")
    parser.add_argument("--applications-dir", type=Path, help="自定义桌面入口安装目录")
    args = parser.parse_args(argv)
    if not sys.platform.startswith("linux"):
        parser.error("此桌面入口安装脚本仅适用于 Linux")
    try:
        target = install_desktop(Path(__file__).resolve().parents[1], args.executable, args.applications_dir)
    except (OSError, ValueError) as error:
        print(f"安装失败：{error}", file=sys.stderr)
        return 1
    print(f"已安装桌面入口：{target}")
    print("现在可在应用菜单中搜索 MD2HTML。移动项目后请重新运行此脚本。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
