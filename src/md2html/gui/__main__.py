from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure /usr/lib/python3/dist-packages is in sys.path if not already present
for dist_path in ("/usr/lib/python3/dist-packages", "/usr/lib/python3.10/dist-packages"):
    if os.path.isdir(dist_path) and dist_path not in sys.path:
        sys.path.append(dist_path)

from .api import BridgeAPI  # noqa: E402
from .settings import load_gui_settings, save_gui_settings  # noqa: E402

WEB_DIR = Path(__file__).parent / "web"
INDEX_HTML = WEB_DIR / "index.html"


def main() -> int:
    try:
        import webview
    except ImportError:
        print("错误: pywebview 未安装。请运行: pip install pywebview", file=sys.stderr)
        return 1

    settings = load_gui_settings()
    width = settings.get("window_width", 1280)
    height = settings.get("window_height", 900)

    api = BridgeAPI()
    window = webview.create_window(
        title="MD2HTML 离线 HTML 生成器",
        url=str(INDEX_HTML),
        js_api=api,
        width=width,
        height=height,
        min_size=(900, 600),
        text_select=True,
    )
    api.set_window(window)

    def on_closed():
        try:
            save_gui_settings({
                "window_width": window.width,
                "window_height": window.height,
            })
        except Exception:
            pass

    window.events.closed += on_closed

    # Determine best available GUI backend on Linux
    gui_type = None
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("WebKit2", "4.0")
        gui_type = "gtk"
    except Exception:
        try:
            from PyQt5 import QtWebEngineWidgets  # noqa: F401
            gui_type = "qt"
        except Exception:
            gui_type = None

    if gui_type:
        webview.start(gui=gui_type, debug=False)
    else:
        webview.start(debug=False)

    return 0


if __name__ == "__main__":
    sys.exit(main())
