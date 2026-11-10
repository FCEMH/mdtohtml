#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  printf '%s\n' '缺少项目 .venv，请按 README 创建环境。' >&2
  exit 3
fi
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$PROJECT_ROOT/.playwright-browsers}"
cd "$PROJECT_ROOT"
if [[ "$#" -eq 0 ]]; then set -- -q; fi
exec env -u PYTHONPATH "$PYTHON" -m pytest "$@"
