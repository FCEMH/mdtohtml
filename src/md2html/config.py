from __future__ import annotations

import math
from copy import deepcopy
from pathlib import Path

import yaml

from .models import BuildError

DEFAULTS = {
    "version": 1,
    "book": {"title": "", "language": "zh-CN", "description": ""},
    "content": {
        "include": ["**/*.md"],
        "exclude": [],
        "order": [],
        "attachment_dirs": ["assets", "images"],
        "skip_draft": True,
    },
    "render": {
        "theme": "auto",
        "toc_depth": 3,
        "search": True,
        "offline": True,
        "math": "katex",
        "code_highlight": True,
        "image_lightbox": True,
        "strict": False,
    },
    "limits": {"warn_image_mb": 5, "warn_output_mb": 50},
}


def load_config(
    root: Path, path: Path | None = None, overrides: dict | None = None
) -> dict:
    config = deepcopy(DEFAULTS)
    chosen = path if path is not None else root / "md2html.yml"
    if chosen.is_symlink():
        raise BuildError("配置文件不能是符号链接")
    if chosen.exists():
        try:
            data = yaml.safe_load(chosen.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as e:
            raise BuildError(f"无法读取配置 {chosen}: {e}") from e
        if not isinstance(data, dict):
            raise BuildError("配置必须是 YAML 映射")
        if set(data) - set(config):
            raise BuildError(f"未知配置字段: {sorted(set(data) - set(config))}")
        for k, v in data.items():
            if isinstance(config[k], dict):
                if not isinstance(v, dict) or set(v) - set(config[k]):
                    raise BuildError(f"配置 {k} 不是有效字段映射")
                config[k].update(v)
            else:
                config[k] = v
    elif path is not None:
        raise BuildError(f"配置文件不存在: {path}")
    for key, value in (overrides or {}).items():
        if value is not None:
            section, field = key.split(".")
            config[section][field] = value
    if config["version"] != 1:
        raise BuildError("只支持 version: 1")
    for section, values in DEFAULTS.items():
        if not isinstance(values, dict):
            continue
        for key, default in values.items():
            v = config[section][key]
            valid = (
                type(v) is bool
                if type(default) is bool
                else isinstance(v, (int, float)) and not isinstance(v, bool)
                if isinstance(default, (int, float))
                else isinstance(v, type(default))
            )
            if not valid or (
                isinstance(default, list) and not all(isinstance(s, str) for s in v)
            ):
                raise BuildError(f"配置字段 {section}.{key} 类型错误")
    if config["render"]["theme"] not in ("light", "dark", "auto"):
        raise BuildError("theme 必须为 light / dark / auto")
    if (
        not 1 <= config["render"]["toc_depth"] <= 6
        or type(config["render"]["toc_depth"]) is not int
    ):
        raise BuildError("toc_depth 必须是 1–6 的整数")
    if not config["render"]["offline"]:
        raise BuildError("只支持离线输出，render.offline 必须为 true")
    if config["render"]["math"] != "katex":
        raise BuildError("当前数学引擎仅支持 katex")
    if any(not math.isfinite(x) or x <= 0 for x in config["limits"].values()):
        raise BuildError("资源体积阈值必须为正数")
    config["book"]["title"] = config["book"]["title"] or root.name
    return config
