# Dorks Eye v3.0
**Multi-engine dork search with SOCKS5 proxy rotation, AI operators (any LLM) and an MCP server**

Dorks Eye finds pages that search engines have indexed - exposed files, admin panels, open directories,
leaked configs - using search operators ("dorks"). v3.0 rebuilds the tool so it keeps working in 2026 and
beyond, lets **any AI model** operate it, and routes all search traffic through **SOCKS5** (or HTTP) proxies.

> Original tool by Jolanda de Koff | Bulls Eye ([HackingPassion.com](https://hackingpassion.com)). GPLv3.
> Use it only on targets you are authorised to assess, and respect the engines' terms of service.

![Screenshot](Img/dork-eye-banner.png)

## What's new in v3.0

| | |
|---|---|
| **SOCKS5 / proxies** | `--proxy socks5h://host:port` (DNS resolved by the proxy, no leaks), auth (`socks5://user:pass@...`), `tor` shortcut, HTTP proxies, a rotating pool (`--proxy` repeated or `--proxy-file`), and `check-proxy` to see your exit IPs. With a proxy set, the tool never silently falls back to a direct connection. |
| **Any AI as operator** | `dorks-eye agent "..."` - the model writes dorks, runs them, refines, and reports. Works with Claude (Anthropic API), OpenAI, Ollama, LM Studio, llama.cpp, vLLM, OpenRouter, Groq, Gemini, Mistral, DeepSeek, xAI, Together, or any OpenAI-compatible URL. |
| **MCP server** | `dorks-eye mcp` exposes `dork_search` / `list_engines` to any MCP client (Claude Desktop/Code, Cursor, VS Code, LM Studio, Open WebUI, ...). |
| **Built to last** | Scraped engines go through the maintained [`ddgs`](https://pypi.org/project/ddgs/) library (detected at runtime, so library updates don't break it), native Bing/Google scrapers, plus API engines that don't break on HTML changes: self-hosted **SearXNG** and the **Brave Search API**. |
| **Scriptable** | Non-interactive CLI, dork files, retries with proxy rotation, dedup, `--json` to stdout, and `.txt/.csv/.json/.jsonl` output. |

The classic interactive mode is still there: just run `python3 dorks-eye.py`.

## Install

```bash
git clone https://github.com/BullsEye0/dorks-eye.git
cd dorks-eye
python3 -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt                     # everything (search + AI + MCP)
```

Or as a command: `pip install ".[all]"` gives you `dorks-eye` on your PATH (`pip install .` for search only).
Termux works the same way (`pip install -r requirements.txt`, then `python dorks-eye.py`).

## Search

```bash
python3 dorks-eye.py                                   # classic interactive mode
python3 dorks-eye.py engines                           # which engines are available/configured
python3 dorks-eye.py search 'site:example.com ext:sql OR ext:bak' -e bing,duckduckgo -n 20
python3 dorks-eye.py search -f dorks.example.txt -e all -o results.csv
python3 dorks-eye.py search 'intitle:"index of" site:example.com' --json | jq '.[0].results[].url'
```

Engines: `duckduckgo`, `bing`, `brave`, `google`, `startpage` (Google results), `mojeek`, `yahoo`,
`searxng` (set `SEARXNG_URL`), `brave_api` (set `BRAVE_API_KEY`), or `all`. Default: duckduckgo, bing, brave.

**Most reliable long-term setup:** run your own [SearXNG](https://docs.searxng.org/) (enable the JSON
format in its `settings.yml`) and use `-e searxng`. It aggregates Google, Bing, Yandex and more, and you
can point SearXNG's own outgoing traffic at a SOCKS5 proxy too.

## SOCKS5 / proxies

```bash
# Tor (socks5h = hostnames resolved through Tor)
python3 dorks-eye.py search 'site:example.com ext:pdf' --proxy tor
# Authenticated SOCKS5
python3 dorks-eye.py search 'site:example.com ext:pdf' -x socks5://user:pass@203.0.113.10:1080
# Rotate through several proxies (round-robin per request; a failed engine is retried on the next proxy)
python3 dorks-eye.py search -f dorks.txt -x socks5h://10.0.0.2:1080 -x socks5h://10.0.0.3:1080 --retries 2
python3 dorks-eye.py search -f dorks.txt --proxy-file proxies.example.txt
# Check exit IPs
python3 dorks-eye.py check-proxy --proxy-file proxies.example.txt
# Or set it once
export DORKSEYE_PROXY=socks5h://127.0.0.1:9050
```

Use `socks5h://` rather than `socks5://` when you want DNS lookups to go through the proxy as well.
A bare `host:port` is treated as `socks5h://host:port`.

## Let an AI operate it

The agent gets two tools (`dork_search`, `list_engines`), a search budget (`--max-searches`, default 15),
and instructions to stay in the scope you give it. Put the scope (your domain) in the objective.

```bash
# Claude (default provider) - export ANTHROPIC_API_KEY=...
python3 dorks-eye.py agent "Audit example.com for exposed backups, configs and open directories"

# Fully local with Ollama (any tool-calling model you've pulled)
python3 dorks-eye.py agent -p ollama -m qwen3 "Find login portals on example.com"

# OpenAI / OpenRouter / Groq / Gemini / Mistral / DeepSeek / xAI / Together / LM Studio / llama.cpp / vLLM
python3 dorks-eye.py agent -p openrouter -m <model-id> "..."        # OPENROUTER_API_KEY
python3 dorks-eye.py agent -p gemini -m <model-id> "..."            # GEMINI_API_KEY

# Any other OpenAI-compatible endpoint
python3 dorks-eye.py agent --base-url http://10.0.0.5:9000/v1 --api-key-env MY_KEY -m my-model "..."

# Search through Tor, keep chatting afterwards, save everything the AI found
python3 dorks-eye.py agent -p ollama -m qwen3 --proxy tor -i -o findings.jsonl "..."

# Send the AI API traffic through a proxy too (separate from the search proxy)
python3 dorks-eye.py agent --llm-proxy socks5h://127.0.0.1:1080 "..."
```

Defaults can come from the environment: `DORKSEYE_PROVIDER`, `DORKSEYE_MODEL`, `DORKSEYE_BASE_URL`.
The Claude backend defaults to `claude-opus-5-5` (`--effort low|medium|high|xhigh|max` to trade depth for
cost) and enables the API's server-side refusal fallback on models that support it.
For other providers pick a model that supports tool/function calling.

## Use it from any MCP client

```bash
python3 dorks-eye.py mcp                        # stdio
python3 dorks-eye.py mcp --proxy tor -e all     # every AI search goes through Tor
python3 dorks-eye.py mcp --transport streamable-http
```

Example client config (Claude Desktop, Cursor, etc.):

```json
{
  "mcpServers": {
    "dorks-eye": {
      "command": "/path/to/dorks-eye/venv/bin/python",
      "args": ["/path/to/dorks-eye/dorks-eye.py", "mcp", "--proxy", "socks5h://127.0.0.1:9050"]
    }
  }
}
```

## Tips

* Too many requests in a short time = captchas or IP blocks. Keep `--delay`, rotate proxies, spread
  work over several engines, or use SearXNG / the Brave API.
* Google blocks scrapers hardest. `startpage` gives Google results with fewer blocks.
* Errors per engine are reported (and included in `--json` / the AI's tool results) instead of failing the run.

## Development

```bash
pip install -r requirements.txt pytest
python3 -m pytest -q
```

Layout: `dorkseye/engines.py` (engines), `proxy.py` (SOCKS5/rotation), `output.py`, `cli.py`,
`ai/` (tool schema + Claude and OpenAI-compatible operators), `mcp_server.py`.

****

## A collection of Dorks:

13,760 dorks that work across all search engines. Updated regularly.

* https://github.com/BullsEye0/google_dork_list

****

![Screenshot](Img/banner_dork-list.png)
****

## Video Dorks Eye on YouTube:

New video coming soon showing v2.0 with all 5 search engines!

****

# Contact

Social Networks - Connect

* Website: [HackingPassion.com](https://hackingpassion.com)
* [Facebook Personal](https://www.facebook.com/profile.php?id=100069546190609)
* [LinkedIn](https://www.linkedin.com/in/jolandadekoff/)
* [YouTube](https://www.youtube.com/@HackingPassion)
* [Facebook Page](https://www.facebook.com/ethical.hack.group)
* [Facebook Group](https://www.facebook.com/groups/ethical.hack.group/)

***

## 💻 Support this project

If you find this tool useful, consider supporting my work:  
[❤️ Sponsor BullsEye](https://github.com/sponsors/BullsEye0)

**Want to learn ethical hacking from scratch?**

Want to master ethical hacking from zero to expert?
Check out my complete ethical hacking course:

**[Ethical Hacking Complete Course – Zero to Expert](https://www.udemy.com/course/ethical-hacking-complete-course-zero-to-expert/?couponCode=DECEMBER25)**  
(This link supports me directly as your instructor)

HACKING IS NOT A HOBBY, BUT A WAY OF LIFE 🎯

***

## Donate

I developed Dorks Eye because I'm passionate about this. Donations are one of the many ways to support what I do.

[Donate](https://hackingpassion.com/donate/)

BAT: Use [Brave](https://brave.com/bul891) and donate on any of my web pages/profiles

[![Donate](https://img.shields.io/badge/Donate-PayPal-green.svg)](https://www.paypal.com/cgi-bin/webscr?cmd=_s-xclick&hosted_button_id=R96YN2PUS8V8W)
