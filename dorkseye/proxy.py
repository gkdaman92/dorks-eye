"""Proxy handling: SOCKS5 / SOCKS5h / SOCKS4 / HTTP(S), single proxy or rotating pool.

`socks5h://` resolves DNS on the proxy side (use it for Tor so DNS doesn't leak).
A plain `host:port` is treated as `socks5h://host:port`.
"""

from __future__ import annotations

import itertools
import os
import threading
from typing import Iterable, Optional
from urllib.parse import urlparse

SUPPORTED_SCHEMES = ("socks5", "socks5h", "socks4", "socks4a", "http", "https")
ENV_VAR = "DORKSEYE_PROXY"
# Tor shortcut: --proxy tor
ALIASES = {"tor": "socks5h://127.0.0.1:9050", "tor-browser": "socks5h://127.0.0.1:9150"}


class ProxyError(ValueError):
    pass


def normalize(proxy: str) -> str:
    """Return a canonical proxy URL or raise ProxyError."""
    proxy = proxy.strip()
    if not proxy:
        raise ProxyError("empty proxy")
    proxy = ALIASES.get(proxy.lower(), proxy)
    if "://" not in proxy:
        proxy = f"socks5h://{proxy}"
    parsed = urlparse(proxy)
    if parsed.scheme.lower() not in SUPPORTED_SCHEMES:
        raise ProxyError(f"unsupported proxy scheme '{parsed.scheme}' (use one of {', '.join(SUPPORTED_SCHEMES)})")
    if not parsed.hostname or not parsed.port:
        raise ProxyError(f"proxy must include host and port: {proxy}")
    return proxy


def mask(proxy: Optional[str]) -> str:
    """Hide credentials when printing a proxy URL."""
    if not proxy:
        return "none (direct)"
    p = urlparse(proxy)
    if p.username or p.password:
        return f"{p.scheme}://***:***@{p.hostname}:{p.port}"
    return proxy


def load_file(path: str) -> list[str]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(normalize(line))
    if not out:
        raise ProxyError(f"no proxies found in {path}")
    return out


class ProxyPool:
    """Thread-safe round-robin over zero or more proxies. Empty pool = direct connection."""

    def __init__(self, proxies: Iterable[str] = ()):
        self.proxies = [normalize(p) for p in proxies]
        self._cycle = itertools.cycle(self.proxies) if self.proxies else None
        self._lock = threading.Lock()

    @classmethod
    def from_args(cls, proxies: Iterable[str] | None = None, proxy_file: str | None = None) -> "ProxyPool":
        items = list(proxies or [])
        if proxy_file:
            items.extend(load_file(proxy_file))
        if not items and os.environ.get(ENV_VAR):
            items = [p for p in os.environ[ENV_VAR].split(",") if p.strip()]
        return cls(items)

    def next(self) -> Optional[str]:
        if not self._cycle:
            return None
        with self._lock:
            return next(self._cycle)

    def __bool__(self) -> bool:
        return bool(self.proxies)

    def __len__(self) -> int:
        return len(self.proxies)


def requests_proxies(proxy: Optional[str]) -> Optional[dict]:
    return {"http": proxy, "https": proxy} if proxy else None


def check(proxy: Optional[str], timeout: float = 15.0) -> dict:
    """Return the public IP seen through `proxy` (None = direct)."""
    import requests

    r = requests.get("https://api.ipify.org?format=json", proxies=requests_proxies(proxy), timeout=timeout)
    r.raise_for_status()
    return r.json()
