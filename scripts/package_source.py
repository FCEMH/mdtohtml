"""Create an allowlisted, dependency-cache-free deliverable ZIP."""

import argparse
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, default=root / "dist/md2html-source.zip")
args = parser.parse_args()
args.output.parent.mkdir(parents=True, exist_ok=True)
roots = ["src", "tests", "docs", "examples", "scripts"]
files = [
    "README.md",
    "md2html.desktop.in",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    ".gitignore",
    "requirements-dev.lock",
]
paths = [root / f for f in files]
for directory in roots:
    paths.extend(
        p
        for p in (root / directory).rglob("*")
        if p.is_file()
        and not any(
            x in {"__pycache__", ".pytest_cache"} or x.endswith(".egg-info")
            for x in p.parts
        )
        and p.suffix != ".pyc"
    )
with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(set(paths)):
        if path.is_file():
            archive.write(path, Path("md2html") / path.relative_to(root))
print(args.output.resolve())
