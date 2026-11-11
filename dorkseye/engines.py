"""Search engine layer.

Scraping-based engines go through the `ddgs` metasearch library, which is actively
maintained and gets parser fixes when engines change their HTML - that is what keeps
this tool working over time instead of hand-written BeautifulSoup selectors that rot.

API-based engines (SearXNG, Brave Search API) are the most durable option: they don't
break when a results page is redesigned and don't hit bot walls.
"""

from __future__ import annotations

import base64
import binascii
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable, Optional
from urllib.parse import parse_qs, urlparse

import requests

from .proxy import ProxyPool, requests_proxies

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"


@dataclass
class Result:
    url: str
    title: str = ""
    snippet: str = ""
    engine: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EngineInfo:
    name: str
    description: str
    kind: str  # "scrape" or "api"
    needs: str = ""  # env var required, if any

    def available(self) -> bool:
        return not self.needs or bool(os.environ.get(self.needs))


# Descriptions for ddgs backends. Which ones exist is detected at runtime, because ddgs
# adds/removes backends between releases (e.g. 9.x dropped google/bing/yandex).
DDGS_DESCRIPTIONS = {
    "duckduckgo": "DuckDuckGo - reliable, privacy-focused",
    "brave": "Brave Search - independent index",
    "mojeek": "Mojeek - independent crawler",
    "startpage": "Startpage - Google results via proxy",
    "yahoo": "Yahoo - Bing-backed",
    "yandex": "Yandex - different index, good for non-English targets",
}
# Not useful for dorking (encyclopedia lookups, no operator support).
DDGS_SKIP = {"wikipedia", "grokipedia", "annasarchive"}


def _ddgs_backends() -> list[str]:
    try:
        from ddgs.engines import ENGINES as _E

        return [k for k in _E.get("text", {}) if k not in DDGS_SKIP]
    except Exception:  # pragma: no cover - ddgs missing or internals changed
        return ["duckduckgo", "brave", "mojeek", "startpage", "yahoo"]


DDGS_ENGINES = {k: DDGS_DESCRIPTIONS.get(k, f"{k} (via ddgs)") for k in _ddgs_backends()}

ENGINES: dict[str, EngineInfo] = {
    name: EngineInfo(name, desc, "scrape") for name, desc in DDGS_ENGINES.items()
}
# Native scrapers for engines ddgs no longer ships - these always honour the proxy.
ENGINES.setdefault("bing", EngineInfo("bing", "Bing - large index, good filetype: support", "scrape"))
ENGINES.setdefault("google", EngineInfo("google", "Google - best results, most aggressive bot blocking", "scrape"))
ENGINES["searxng"] = EngineInfo(
    "searxng", "SearXNG instance JSON API (self-host; aggregates Google/Bing/Yandex/...)", "api", "SEARXNG_URL"
)
ENGINES["brave_api"] = EngineInfo("brave_api", "Brave Search official API", "api", "BRAVE_API_KEY")

DEFAULT_ENGINES = [e for e in ("duckduckgo", "bing", "brave") if e in ENGINES]


class EngineError(RuntimeError):
    pass


def _session(proxy: Optional[str]) -> requests.Session:
    s = requests.Session()
    s.trust_env = not proxy  # with an explicit proxy, never fall back to env proxies
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    if proxy:
        s.proxies.update(requests_proxies(proxy))
    return s


def _ddgs_search(backend: str, dork: str, amount: int, proxy: Optional[str], timeout: int) -> list[Result]:
    try:
        from ddgs import DDGS
    except ImportError as e:  # pragma: no cover
        raise EngineError("ddgs is not installed: pip install ddgs") from e
    if backend not in DDGS_ENGINES:
        # ddgs silently falls back to "auto" for unknown backends - never let that happen.
        raise EngineError(f"backend '{backend}' is not provided by the installed ddgs")

    with DDGS(proxy=proxy, timeout=timeout) as d:
        rows = d.text(dork, backend=backend, max_results=amount) or []
    return [
        Result(url=r.get("href", ""), title=r.get("title", ""), snippet=r.get("body", ""), engine=backend)
        for r in rows
        if r.get("href")
    ]


def _bing_real_url(href: str) -> str:
    """Bing wraps results as bing.com/ck/a?...&u=a1<base64url>; unwrap them."""
    if "bing.com/ck/a" not in href:
        return href
    u = parse_qs(urlparse(href).query).get("u", [""])[0]
    if u.startswith("a1"):
        b = u[2:]
        try:
            return base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode("utf-8", "replace")
        except (ValueError, binascii.Error):
            return href
    return href


def _bing_search(dork: str, amount: int, proxy: Optional[str], timeout: int) -> list[Result]:
    from bs4 import BeautifulSoup

    out: list[Result] = []
    seen: set[str] = set()
    with _session(proxy) as s:
        first = 1
        while len(out) < amount and first < 200:
            r = s.get("https://www.bing.com/search", params={"q": dork, "first": first, "count": 30}, timeout=timeout)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            items = soup.select("li.b_algo")
            if not items:
                if "captcha" in r.text.lower():
                    raise EngineError("Bing returned a captcha (rotate proxy / slow down)")
                break
            new = 0
            for li in items:
                a = li.select_one("h2 a[href]")
                if not a:
                    continue
                url = _bing_real_url(a["href"])
                if not url.startswith("http") or url in seen:
                    continue
                seen.add(url)
                new += 1
                snip = li.select_one(".b_caption p, p")
                out.append(Result(url=url, title=a.get_text(" ", strip=True),
                                  snippet=snip.get_text(" ", strip=True) if snip else "", engine="bing"))
            if not new:
                break
            first += len(items)
    return out[:amount]


def _google_search(dork: str, amount: int, proxy: Optional[str], timeout: int) -> list[Result]:
    from bs4 import BeautifulSoup

    out: list[Result] = []
    seen: set[str] = set()
    with _session(proxy) as s:
        s.cookies.set("CONSENT", "PENDING+987", domain=".google.com")
        s.cookies.set("SOCS", "CAESHAgBEhIaAB", domain=".google.com")
        start = 0
        while len(out) < amount and start < 100:
            r = s.get("https://www.google.com/search",
                      params={"q": dork, "num": min(amount + 2, 100), "start": start, "hl": "en"}, timeout=timeout)
            if r.status_code == 429 or "/sorry/" in r.url:
                raise EngineError("Google rate-limited this IP (429/sorry page) - rotate proxy or use startpage/searxng")
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            new = 0
            for a in soup.select("a[href]"):
                href = a["href"]
                if href.startswith("/url?"):
                    href = parse_qs(urlparse(href).query).get("q", [""])[0]
                if not href.startswith("http") or "google." in urlparse(href).netloc or href in seen:
                    continue
                h3 = a.find("h3")
                if not h3:
                    continue
                seen.add(href)
                new += 1
                out.append(Result(url=href, title=h3.get_text(" ", strip=True), engine="google"))
            if not new:
                if not out and "enablejs" in r.text.lower():
                    raise EngineError("Google served a JavaScript-only page - use startpage or searxng instead")
                break
            start += 10
    return out[:amount]


def _searxng_search(dork: str, amount: int, proxy: Optional[str], timeout: int) -> list[Result]:
    base = os.environ.get("SEARXNG_URL")
    if not base:
        raise EngineError("set SEARXNG_URL (e.g. http://127.0.0.1:8888) to use searxng")
    out: list[Result] = []
    page = 1
    with _session(proxy) as s:
        while len(out) < amount and page <= 5:
            r = s.get(base.rstrip("/") + "/search", params={"q": dork, "format": "json", "pageno": page}, timeout=timeout)
            r.raise_for_status()
            rows = r.json().get("results", [])
            if not rows:
                break
            out += [
                Result(url=x["url"], title=x.get("title", ""), snippet=x.get("content", ""), engine="searxng")
                for x in rows
                if x.get("url")
            ]
            page += 1
    return out[:amount]


def _brave_api_search(dork: str, amount: int, proxy: Optional[str], timeout: int) -> list[Result]:
    key = os.environ.get("BRAVE_API_KEY")
    if not key:
        raise EngineError("set BRAVE_API_KEY to use brave_api")
    out: list[Result] = []
    offset = 0
    with _session(proxy) as s:
        while len(out) < amount and offset <= 9:
            r = s.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": dork, "count": min(20, amount), "offset": offset},
                headers={"Accept": "application/json", "X-Subscription-Token": key},
                timeout=timeout,
            )
            r.raise_for_status()
            rows = (r.json().get("web") or {}).get("results", [])
            if not rows:
                break
            out += [
                Result(url=x["url"], title=x.get("title", ""), snippet=x.get("description", ""), engine="brave_api")
                for x in rows
                if x.get("url")
            ]
            offset += 1
    return out[:amount]


def search_one(engine: str, dork: str, amount: int, proxy: Optional[str] = None, timeout: int = 15) -> list[Result]:
    """Run one dork on one engine. Raises EngineError on failure."""
    engine = engine.lower().strip()
    try:
        if engine in DDGS_ENGINES:
            return _ddgs_search(engine, dork, amount, proxy, timeout)
        if engine == "bing":
            return _bing_search(dork, amount, proxy, timeout)
        if engine == "google":
            return _google_search(dork, amount, proxy, timeout)
        if engine == "searxng":
            return _searxng_search(dork, amount, proxy, timeout)
        if engine == "brave_api":
            return _brave_api_search(dork, amount, proxy, timeout)
    except EngineError:
        raise
    except Exception as e:  # network errors, blocks, parser errors
        raise EngineError(f"{type(e).__name__}: {e}") from e
    raise EngineError(f"unknown engine '{engine}' (available: {', '.join(ENGINES)})")


def resolve_engines(names: Iterable[str] | str | None) -> list[str]:
    if names is None:
        return list(DEFAULT_ENGINES)
    if isinstance(names, str):
        names = names.split(",")
    names = [n.strip().lower() for n in names if n and n.strip()]
    if not names:
        return list(DEFAULT_ENGINES)
    if "all" in names:
        return [n for n, info in ENGINES.items() if info.available()]
    unknown = [n for n in names if n not in ENGINES]
    if unknown:
        raise EngineError(f"unknown engine(s): {', '.join(unknown)} (available: {', '.join(ENGINES)})")
    return names


@dataclass
class SearchReport:
    dork: str
    results: list[Result] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"dork": self.dork, "results": [r.to_dict() for r in self.results], "errors": self.errors}


def search(
    dork: str,
    engines: Iterable[str] | str | None = None,
    amount: int = 10,
    pool: Optional[ProxyPool] = None,
    timeout: int = 15,
    delay: float = 2.0,
    retries: int = 1,
    dedupe: bool = True,
    on_result: Optional[Callable[[Result], None]] = None,
    on_status: Optional[Callable[[str], None]] = None,
) -> SearchReport:
    """Run `dork` across engines, rotating proxies (if any) per request.

    On failure an engine is retried `retries` times with the next proxy in the pool.
    """
    pool = pool or ProxyPool()
    names = resolve_engines(engines)
    report = SearchReport(dork=dork)
    seen: set[str] = set()

    for i, name in enumerate(names):
        if i and delay > 0:
            time.sleep(delay)
        if on_status:
            on_status(f"Searching {name}...")
        last_err = None
        for attempt in range(retries + 1):
            proxy = pool.next()
            try:
                rows = search_one(name, dork, amount, proxy=proxy, timeout=timeout)
                last_err = None
                break
            except EngineError as e:
                last_err = str(e)
                if attempt < retries:
                    time.sleep(min(2 ** attempt, 8))
        if last_err is not None:
            report.errors[name] = last_err
            if on_status:
                on_status(f"{name}: {last_err}")
            continue
        if not rows and on_status:
            on_status(f"{name}: no results")
        for r in rows:
            key = r.url.rstrip("/")
            if dedupe and key in seen:
                continue
            seen.add(key)
            report.results.append(r)
            if on_result:
                on_result(r)
    return report
