"""Provider-neutral tool definitions + executor shared by every AI backend and the MCP server."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Optional

from .. import engines as eng
from ..output import save
from ..proxy import ProxyPool

SYSTEM_PROMPT = """You are the operator of Dorks Eye, a search-engine dorking tool used for OSINT and \
authorized security assessments (attack-surface discovery, exposed-file audits, bug bounty recon).

How to work:
- Turn the user's objective into precise search dorks (site:, inurl:, intitle:, intext:, filetype:/ext:, \
quotes, -exclusions, OR). Different engines support different operators: Google/Startpage/Brave handle \
most; Bing prefers `filetype:` and `inbody:`; DuckDuckGo supports site:/filetype:/intitle:/inurl:.
- Call `dork_search` to run each dork. Start broad, then refine based on what comes back. Avoid \
near-duplicate queries; every call hits real search engines.
- Stay within the scope the user gives you (their domains/organisation). If no scope is given for a \
target-specific objective, ask for one instead of guessing.
- Do not try to log in, exploit, or download anything; you only search and report.
- Finish with a concise report: the dorks you ran, the notable URLs grouped by finding type, and \
suggested next dorks. Never invent URLs - only report what the tool returned."""

DORK_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "The dork / search query to run."},
        "engines": {
            "type": "array",
            "items": {"type": "string", "enum": list(eng.ENGINES) + ["all"]},
            "description": "Engines to query. Omit to use the configured defaults.",
        },
        "max_results": {
            "type": "integer",
            "minimum": 1,
            "maximum": 50,
            "description": "Max results per engine (default 10).",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}

LIST_ENGINES_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}

TOOLS = [
    {
        "name": "dork_search",
        "description": (
            "Run a search dork across one or more search engines (through the configured SOCKS5/HTTP "
            "proxy, if any) and return deduplicated results as JSON: url, title, snippet, engine, "
            "plus per-engine errors (blocked/captcha/timeouts)."
        ),
        "schema": DORK_SEARCH_SCHEMA,
    },
    {
        "name": "list_engines",
        "description": "List the available search engines, which are configured, and the defaults.",
        "schema": LIST_ENGINES_SCHEMA,
    },
]


@dataclass
class ToolExecutor:
    pool: ProxyPool = field(default_factory=ProxyPool)
    default_engines: Optional[list[str]] = None
    max_results: int = 10
    timeout: int = 15
    delay: float = 2.0
    max_searches: int = 15
    output_path: Optional[str] = None
    on_event: Optional[Callable[[str], None]] = None
    searches_run: int = 0
    all_results: dict[str, eng.Result] = field(default_factory=dict)

    def _log(self, msg: str) -> None:
        if self.on_event:
            self.on_event(msg)

    def list_engines(self) -> dict:
        return {
            "engines": [
                {"name": i.name, "description": i.description, "type": i.kind, "configured": i.available()}
                for i in eng.ENGINES.values()
            ],
            "defaults": self.default_engines or eng.DEFAULT_ENGINES,
            "proxy": "enabled" if self.pool else "direct",
        }

    def dork_search(self, query: str, engines=None, max_results: Optional[int] = None) -> dict:
        if not isinstance(query, str) or not query.strip():
            return {"error": "query must be a non-empty string"}
        if self.searches_run >= self.max_searches:
            return {"error": f"search budget exhausted ({self.max_searches} searches). Write your report now."}
        try:
            n = int(max_results) if max_results is not None else self.max_results
        except (TypeError, ValueError):
            n = self.max_results
        n = max(1, min(n, 50))
        try:
            names = eng.resolve_engines(engines or self.default_engines)
        except eng.EngineError as e:
            return {"error": str(e)}

        self.searches_run += 1
        self._log(f"dork_search[{self.searches_run}/{self.max_searches}] {query!r} on {','.join(names)}")
        report = eng.search(
            query, names, n, pool=self.pool, timeout=self.timeout, delay=self.delay, on_status=None
        )
        for r in report.results:
            self.all_results.setdefault(r.url, r)
        if self.output_path and report.results:
            save(self.output_path, query, report.results)
        self._log(f"  -> {len(report.results)} results" + (f", errors: {report.errors}" if report.errors else ""))
        out = report.to_dict()
        out["searches_remaining"] = self.max_searches - self.searches_run
        return out

    def call(self, name: str, args: dict | str | None) -> str:
        """Execute a tool call and return a JSON string for the model."""
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                return json.dumps({"error": "arguments were not valid JSON"})
        args = args or {}
        if not isinstance(args, dict):
            return json.dumps({"error": "arguments must be an object"})
        if name == "dork_search":
            res = self.dork_search(args.get("query", ""), args.get("engines"), args.get("max_results"))
        elif name == "list_engines":
            res = self.list_engines()
        else:
            res = {"error": f"unknown tool {name}"}
        return json.dumps(res, ensure_ascii=False)
