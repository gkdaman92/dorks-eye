import json
from types import SimpleNamespace

import pytest

from dorkseye import engines as eng
from dorkseye.ai.tools import ToolExecutor
from dorkseye.output import save
from dorkseye.proxy import ProxyError, ProxyPool, mask, normalize


def test_normalize_proxies():
    assert normalize("127.0.0.1:9050") == "socks5h://127.0.0.1:9050"
    assert normalize("tor") == "socks5h://127.0.0.1:9050"
    assert normalize("socks5://u:p@h:1080") == "socks5://u:p@h:1080"
    with pytest.raises(ProxyError):
        normalize("ftp://h:1")
    with pytest.raises(ProxyError):
        normalize("socks5://hostonly")


def test_mask_hides_credentials():
    assert mask("socks5://u:p@h:1080") == "socks5://***:***@h:1080"
    assert mask(None).startswith("none")


def test_pool_rotates_and_reads_env(monkeypatch, tmp_path):
    pool = ProxyPool(["a:1", "b:2"])
    assert [pool.next() for _ in range(3)] == ["socks5h://a:1", "socks5h://b:2", "socks5h://a:1"]
    assert ProxyPool().next() is None
    monkeypatch.setenv("DORKSEYE_PROXY", "c:3")
    assert ProxyPool.from_args().proxies == ["socks5h://c:3"]
    f = tmp_path / "p.txt"
    f.write_text("# comment\nd:4\n\n")
    assert ProxyPool.from_args(None, str(f)).proxies == ["socks5h://d:4"]


def test_resolve_engines():
    assert eng.resolve_engines(None) == eng.DEFAULT_ENGINES
    assert eng.resolve_engines("bing, google") == ["bing", "google"]
    with pytest.raises(eng.EngineError):
        eng.resolve_engines("nope")


def test_search_dedupes_rotates_and_collects_errors(monkeypatch):
    calls = []

    def fake(engine, dork, amount, proxy=None, timeout=15):
        calls.append((engine, proxy))
        if engine == "google":
            raise eng.EngineError("blocked")
        return [eng.Result(url="https://x.test/a", engine=engine), eng.Result(url=f"https://{engine}.test/", engine=engine)]

    monkeypatch.setattr(eng, "search_one", fake)
    rep = eng.search("q", "bing,google,duckduckgo", 5, pool=ProxyPool(["a:1", "b:2"]), delay=0, retries=1)
    assert [r.url for r in rep.results] == ["https://x.test/a", "https://bing.test/", "https://duckduckgo.test/"]
    assert "google" in rep.errors
    # google retried once with the next proxy
    assert [c for c in calls if c[0] == "google"] == [("google", "socks5h://b:2"), ("google", "socks5h://a:1")]


def test_executor_budget_and_bad_args(monkeypatch):
    monkeypatch.setattr(eng, "search_one", lambda *a, **k: [eng.Result(url="https://x.test/", engine="bing")])
    ex = ToolExecutor(max_searches=1, delay=0)
    out = json.loads(ex.call("dork_search", '{"query": "site:x.test", "engines": ["bing"]}'))
    assert out["results"][0]["url"] == "https://x.test/"
    assert "budget" in json.loads(ex.call("dork_search", {"query": "again"}))["error"]
    assert "error" in json.loads(ex.call("dork_search", "{not json"))
    assert "error" in json.loads(ex.call("nope", {}))
    assert json.loads(ex.call("list_engines", {}))["engines"]


@pytest.mark.parametrize("ext", ["txt", "csv", "json", "jsonl"])
def test_save_formats(tmp_path, ext):
    p = tmp_path / f"out.{ext}"
    rs = [eng.Result(url="https://x.test/", title="t", engine="bing")]
    save(str(p), "d1", rs)
    save(str(p), "d2", rs)
    text = p.read_text()
    assert "https://x.test/" in text
    if ext == "json":
        assert len(json.loads(text)) == 2


def _oa_msg(content=None, tool_calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))])


def test_openai_compat_tool_loop(monkeypatch):
    from dorkseye.ai.openai_compat import OpenAICompatAgent

    monkeypatch.setattr(eng, "search_one", lambda *a, **k: [eng.Result(url="https://x.test/", engine="bing")])
    agent = OpenAICompatAgent(ToolExecutor(delay=0), provider="ollama", model="test-model")
    tc = SimpleNamespace(id="c1", function=SimpleNamespace(name="dork_search", arguments='{"query":"site:x.test"}'))
    replies = iter([_oa_msg(tool_calls=[tc]), _oa_msg(content="Found https://x.test/")])
    seen = []

    def create(**kw):
        seen.append([m["role"] for m in kw["messages"]])
        return next(replies)

    monkeypatch.setattr(agent.client.chat.completions, "create", create)
    assert agent.run("find stuff on x.test") == "Found https://x.test/"
    assert seen[1] == ["system", "user", "assistant", "tool"]


def test_anthropic_tool_loop(monkeypatch):
    from dorkseye.ai.anthropic_agent import AnthropicAgent

    monkeypatch.setattr(eng, "search_one", lambda *a, **k: [eng.Result(url="https://x.test/", engine="bing")])
    agent = AnthropicAgent(ToolExecutor(delay=0), api_key="test")
    blk = lambda **kw: SimpleNamespace(**kw)  # noqa: E731
    replies = iter([
        SimpleNamespace(stop_reason="tool_use", content=[blk(type="tool_use", id="t1", name="dork_search", input={"query": "q"})]),
        SimpleNamespace(stop_reason="end_turn", content=[blk(type="text", text="report")]),
    ])
    sent = []
    monkeypatch.setattr(agent, "_create", lambda: (sent.append(list(agent.messages)), next(replies))[1])
    assert agent.run("go") == "report"
    tool_msg = sent[1][-1]
    assert tool_msg["role"] == "user" and tool_msg["content"][0]["type"] == "tool_result"


def test_mcp_server_builds():
    pytest.importorskip("mcp")
    from dorkseye.mcp_server import build_server

    assert build_server(ToolExecutor()) is not None


def test_cli_parses():
    from dorkseye.cli import build_parser

    a = build_parser().parse_args(["search", "site:x", "-x", "tor", "-x", "h:1", "-e", "bing", "-o", "o.csv"])
    assert a.proxy == ["tor", "h:1"] and a.engines == "bing"
    a = build_parser().parse_args(["agent", "find", "x", "-p", "ollama", "-m", "qwen3", "--llm-proxy", "tor"])
    assert a.provider == "ollama" and a.objective == ["find", "x"]


def test_bing_unwraps_ck_links():
    import base64

    target = "https://example.com/a?b=1"
    enc = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    assert eng._bing_real_url(f"https://www.bing.com/ck/a?!&&p=x&u=a1{enc}&ntb=1") == target
    assert eng._bing_real_url("https://plain.test/") == "https://plain.test/"


def test_bing_parser(monkeypatch):
    html = """<ol><li class="b_algo"><h2><a href="https://r.test/1">One</a></h2><p>snip</p></li>
              <li class="b_algo"><h2><a href="https://r.test/2">Two</a></h2></li></ol>"""

    class Resp:
        status_code, text, url = 200, html, "https://www.bing.com/search"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(eng.requests.Session, "get", lambda self, *a, **k: Resp())
    rs = eng._bing_search("q", 5, None, 5)
    assert [r.url for r in rs] == ["https://r.test/1", "https://r.test/2"] and rs[0].snippet == "snip"


def test_unknown_ddgs_backend_never_falls_back():
    with pytest.raises(eng.EngineError):
        eng._ddgs_search("not-a-backend", "q", 1, None, 1)
