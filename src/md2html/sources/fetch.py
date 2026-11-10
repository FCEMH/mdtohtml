from __future__ import annotations

import ipaddress
import socket
import urllib.parse
import urllib.request
from typing import Tuple

from ..models import BuildError
from .proxy import desktop_proxy_handler

DEFAULT_TIMEOUT = 15
MAX_HTML_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_ASSET_BYTES = 30 * 1024 * 1024  # 30 MB


def is_safe_url(url: str, allowed_hosts: tuple[str, ...] | None = None) -> bool:
    """Validate URL protocol and ensure destination IP is not private/loopback (SSRF protection)."""
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False

    if allowed_hosts:
        if not any(
            host == allowed or host.endswith("." + allowed) for allowed in allowed_hosts
        ):
            return False

    try:
        # Resolve hostname to check IP addresses
        addr_infos = socket.getaddrinfo(host, None)
        for addr in addr_infos:
            ip_str = addr[4][0]
            ip = ipaddress.ip_address(ip_str)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
            ):
                return False
    except (socket.gaierror, ValueError):
        return False
    return True


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: tuple[str, ...] | None = None):
        super().__init__()
        self.allowed_hosts = allowed_hosts
        self.redirect_count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.redirect_count += 1
        if self.redirect_count > 5:
            raise BuildError("重定向次数过多", 2)
        if not is_safe_url(newurl, self.allowed_hosts):
            raise BuildError(f"重定向到不安全或未允许的地址: {newurl}", 2)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_url(
    url: str,
    max_bytes: int = MAX_HTML_BYTES,
    timeout: int = DEFAULT_TIMEOUT,
    allowed_hosts: tuple[str, ...] | None = None,
) -> Tuple[bytes, str]:
    """Fetch URL with SSRF protection, redirect verification, size limits, and custom user agent."""
    if not is_safe_url(url, allowed_hosts):
        raise BuildError(f"URL 验证失败或目标为主机内网/私有地址: {url}", 2)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36 MD2HTML/0.1"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(
        desktop_proxy_handler(), SafeRedirectHandler(allowed_hosts)
    )

    try:
        with opener.open(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise BuildError(f"内容大小超过限制 ({max_bytes} 字节)", 2)
            return data, content_type
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise BuildError("分享内容不存在或已失效 (HTTP 404)", 2) from e
        elif e.code in (401, 403):
            raise BuildError("分享内容需要登录或无权限访问 (HTTP 401/403)", 2) from e
        else:
            raise BuildError(f"获取网页失败 (HTTP {e.code})", 2) from e
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise BuildError(
                f"网络连接超时（单次等待 {timeout}s）；请检查网络或系统代理是否可用", 2
            ) from e
        raise BuildError(f"网络连接错误: {e.reason}", 2) from e
    except TimeoutError as e:
        raise BuildError(
            f"网络连接超时（单次等待 {timeout}s）；请检查网络或系统代理是否可用", 2
        ) from e
