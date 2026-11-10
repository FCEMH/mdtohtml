from __future__ import annotations

import ast
import fnmatch
import ipaddress
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request


def _setting(binary: str, schema: str, key: str):
    try:
        result = subprocess.run(
            [binary, "get", schema, key],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=2,
            check=False,
        )
        if result.returncode:
            return None
        value = result.stdout.strip().removeprefix("@as ")
        return ast.literal_eval(value)
    except (OSError, subprocess.TimeoutExpired, ValueError, SyntaxError):
        return None


def _endpoint(host, port) -> str | None:
    if not isinstance(host, str) or type(port) is not int or not 0 < port < 65536:
        return None
    host = host.strip()
    if not host or any(c.isspace() or c in "/\\?#@" for c in host):
        return None
    if ":" in host:
        try:
            host = f"[{ipaddress.IPv6Address(host.strip('[]'))}]"
        except ValueError:
            return None
    # HTTPS targets use CONNECT through an HTTP proxy endpoint as well.
    return f"http://{host}:{port}"


def _gnome_proxies() -> tuple[dict[str, str], list[str]]:
    if not sys.platform.startswith("linux"):
        return {}, []
    binary = shutil.which("gsettings")
    if not binary or _setting(binary, "org.gnome.system.proxy", "mode") != "manual":
        return {}, []

    proxies = {}
    for scheme in ("http", "https"):
        schema = f"org.gnome.system.proxy.{scheme}"
        endpoint = _endpoint(
            _setting(binary, schema, "host"), _setting(binary, schema, "port")
        )
        if endpoint:
            proxies[scheme] = endpoint
    if "http" in proxies and "https" not in proxies:
        proxies["https"] = proxies["http"]
    ignored = _setting(binary, "org.gnome.system.proxy", "ignore-hosts")
    return proxies, [s for s in ignored if isinstance(s, str)] if isinstance(ignored, list) else []


def _bypasses_system_proxy(url: str, rules: list[str]) -> bool:
    host = (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    for rule in rules:
        rule = rule.strip().lower()
        if not rule:
            continue
        if rule == "<local>" and "." not in host and ":" not in host:
            return True
        if "/" in rule:
            try:
                if address is not None and address in ipaddress.ip_network(rule, strict=False):
                    return True
            except ValueError:
                pass
            continue
        domain = rule.removeprefix("*.").lstrip(".")
        if fnmatch.fnmatchcase(host, rule) or host == domain or host.endswith("." + domain):
            return True
    return False


class _DesktopProxyHandler(urllib.request.ProxyHandler):
    def __init__(self, proxies: dict[str, str], system_schemes: set[str], ignored: list[str]):
        self._system_schemes = system_schemes
        self._ignored = ignored
        super().__init__(proxies)

    def proxy_open(self, req, proxy, type):
        if type in self._system_schemes and _bypasses_system_proxy(req.full_url, self._ignored):
            return None
        return super().proxy_open(req, proxy, type)


def desktop_proxy_handler() -> urllib.request.ProxyHandler:
    """Keep native/env proxies; fill absent HTTP(S) settings from GNOME manual mode.

    This reads settings for each request without changing the environment or the
    system. PAC and SOCKS are not interpreted by this HTTP(S) fallback.
    """
    native = urllib.request.getproxies()
    explicit = {name.lower() for name in os.environ if name.lower().endswith("_proxy")}
    if all(scheme in native or f"{scheme}_proxy" in explicit for scheme in ("http", "https")):
        return urllib.request.ProxyHandler(native)

    system, ignored = _gnome_proxies()
    for scheme in ("http", "https"):
        # An explicitly empty env variable also overrides the desktop setting.
        if scheme in native or f"{scheme}_proxy" in explicit:
            system.pop(scheme, None)
    return _DesktopProxyHandler({**system, **native}, set(system), ignored)
