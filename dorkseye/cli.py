"""Command-line interface.

    dorks-eye                                  classic interactive mode
    dorks-eye search 'intitle:"index of" ext:sql' -e bing,duckduckgo -n 20 -o out.csv
    dorks-eye search -f dorks.txt --proxy socks5h://127.0.0.1:9050
    dorks-eye agent "find exposed backup files on example.com" --provider ollama --model qwen3
    dorks-eye mcp                              expose tools to any MCP client
    dorks-eye engines | check-proxy
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import __version__
from . import engines as eng
from .output import save
from .proxy import ProxyError, ProxyPool, check, mask

RED, BLUE, GREEN, YELLOW, END = "\033[91m", "\033[94m", "\033[92m", "\033[93m", "\033[0m"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    RED = BLUE = GREEN = YELLOW = END = ""

BANNER = r"""
    ▓█████▄  ▒█████   ██▀███   ██ ▄█▀  ██████    ▓█████▓██   ██▓▓█████
    ▒██▀ ██▌▒██▒  ██▒▓██ ▒ ██▒ ██▄█▒ ▒██    ▒    ▓█   ▀ ▒██  ██▒▓█   ▀
    ░██   █▌▒██░  ██▒▓██ ░▄█ ▒▓███▄░ ░ ▓██▄      ▒███    ▒██ ██░▒███
    ░▓█▄   ▌▒██   ██░▒██▀▀█▄  ▓██ █▄   ▒   ██▒   ▒▓█  ▄  ░ ▐██▓░▒▓█  ▄
    ░▒████▓ ░ ████▓▒░░██▓ ▒██▒▒██▒ █▄▒██████▒▒   ░▒████▒ ░ ██▒▓░░▒████▒
    ▒▒▓  ▒ ░ ▒░▒░▒░ ░ ▒▓ ░▒▓░▒ ▒▒ ▓▒▒ ▒▓▒ ▒ ░   ░░ ▒░ ░  ██▒▒▒ ░░ ▒░ ░
    ░ ▒  ▒   ░ ▒ ▒░   ░▒ ░ ▒░░ ░▒ ▒░░ ░▒  ░ ░    ░ ░  ░▓██ ░▒░  ░ ░  ░
    ░ ░  ░ ░ ░ ░ ▒    ░░   ░ ░ ░░ ░ ░  ░  ░        ░   ▒ ▒ ░░     ░
    ░        ░ ░     ░     ░  ░         ░        ░  ░░ ░        ░  ░
    ░                                                  ░ ░  v{ver} """

CREDITS = """
                Original author: Jolanda de Koff | Bulls Eye
                Github:  https://github.com/BullsEye0
                Website: https://HackingPassion.com
"""


def err(msg: str) -> None:
    print(f"{RED}[!] {msg}{END}", file=sys.stderr)


def info(msg: str) -> None:
    print(f"{BLUE}[•] {msg}{END}", file=sys.stderr)


def show_banner() -> None:
    print(RED + BANNER.format(ver=__version__) + END)
    print(BLUE + CREDITS + END)


# --------------------------------------------------------------------------- helpers


def build_pool(args) -> ProxyPool:
    try:
        pool = ProxyPool.from_args(args.proxy, args.proxy_file)
    except (ProxyError, OSError) as e:
        err(str(e))
        sys.exit(2)
    return pool


def print_result(i: int, r: eng.Result, verbose: bool = False) -> None:
    print(f"{GREEN}[+]{END} {i:>3} {r.url}  {YELLOW}({r.engine}){END}")
    if verbose and r.title:
        print(f"        {r.title}")


# --------------------------------------------------------------------------- commands


def cmd_search(args) -> int:
    pool = build_pool(args)
    dorks = list(args.dork or [])
    if args.dork_file:
        with open(args.dork_file, encoding="utf-8") as fh:
            dorks += [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    if not dorks:
        err("give a dork or --dork-file")
        return 2
    try:
        names = eng.resolve_engines(args.engines)
    except eng.EngineError as e:
        err(str(e))
        return 2

    if not args.json:
        info(f"Engines: {', '.join(names)} | Proxy: {mask(pool.proxies[0]) if len(pool) == 1 else (f'{len(pool)} rotating' if pool else 'none (direct)')}")

    reports = []
    counter = 0
    for d_i, dork in enumerate(dorks):
        if d_i and args.delay:
            time.sleep(args.delay)
        if not args.json:
            print(f"\n{BLUE}[~] Dork:{END} {dork}")

        def on_result(r):
            nonlocal counter
            counter += 1
            if not args.json:
                print_result(counter, r, args.verbose)

        report = eng.search(
            dork, names, args.amount, pool=pool, timeout=args.timeout, delay=args.delay,
            retries=args.retries, on_result=on_result, on_status=None if args.json else info,
        )
        reports.append(report)
        if args.output and report.results:
            save(args.output, dork, report.results)

    if args.json:
        print(json.dumps([r.to_dict() for r in reports], indent=2, ensure_ascii=False))
    else:
        info(f"Done. {counter} unique results." + (f" Saved to {args.output}" if args.output else ""))
    return 0 if counter else 1


def cmd_engines(args) -> int:
    for info_ in eng.ENGINES.values():
        status = f"{GREEN}ready{END}" if info_.available() else f"{YELLOW}needs {info_.needs}{END}"
        default = " (default)" if info_.name in eng.DEFAULT_ENGINES else ""
        print(f"  {info_.name:<11} {info_.kind:<6} {status}  {info_.description}{default}")
    return 0


def cmd_check_proxy(args) -> int:
    pool = build_pool(args)
    targets = pool.proxies or [None]
    ok = 0
    for p in targets:
        try:
            ip = check(p, timeout=args.timeout)["ip"]
            print(f"{GREEN}[+]{END} {mask(p)} -> exit IP {ip}")
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"{RED}[-]{END} {mask(p)} -> {type(e).__name__}: {e}")
    return 0 if ok == len(targets) else 1


def _executor(args, pool, quiet_stdout=False):
    from .ai.tools import ToolExecutor

    log = (lambda m: print(f"[•] {m}", file=sys.stderr)) if quiet_stdout else info
    return ToolExecutor(
        pool=pool,
        default_engines=eng.resolve_engines(args.engines) if args.engines else None,
        max_results=args.amount,
        timeout=args.timeout,
        delay=args.delay,
        max_searches=getattr(args, "max_searches", 10_000),
        output_path=args.output,
        on_event=None if getattr(args, "quiet", False) else log,
    )


def cmd_agent(args) -> int:
    from .ai import build_agent
    from .proxy import normalize

    pool = build_pool(args)
    executor = _executor(args, pool)
    llm_proxy = normalize(args.llm_proxy) if args.llm_proxy else None
    agent = build_agent(
        args.provider, executor, model=args.model, base_url=args.base_url, api_key_env=args.api_key_env,
        llm_proxy=llm_proxy, effort=args.effort, max_turns=args.max_turns,
    )
    info(f"AI operator: {args.provider} / {agent.model} | search proxy: "
         f"{(f'{len(pool)} rotating' if len(pool) > 1 else mask(pool.proxies[0])) if pool else 'none (direct)'}"
         f" | budget: {args.max_searches} searches")

    objective = " ".join(args.objective).strip()
    if not objective and not args.interactive:
        err("give an objective, or use --interactive")
        return 2

    def turn(text: str) -> None:
        answer = agent.run(text)
        print(f"\n{answer}\n")

    if objective:
        turn(objective)
    if args.interactive:
        info("Interactive mode - type follow-ups, 'exit' to quit.")
        while True:
            try:
                text = input(f"{BLUE}you>{END} ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if text.lower() in ("exit", "quit", "q"):
                break
            if text:
                turn(text)
    if executor.all_results:
        info(f"{len(executor.all_results)} unique URLs collected." + (f" Saved to {args.output}" if args.output else ""))
    return 0


def cmd_mcp(args) -> int:
    from .mcp_server import serve

    pool = build_pool(args)
    # stdout carries the MCP protocol in stdio mode - log to stderr only.
    serve(_executor(args, pool, quiet_stdout=True), transport=args.transport)
    return 0


# --------------------------------------------------------------------------- classic interactive mode


def interactive() -> int:
    show_banner()
    print("\n\t\tHi there, Shall we play a game..? 😃\n")
    names = list(eng.ENGINES)
    try:
        print("  " + "»" * 78 + "\n")
        print("[~] Choose your search engine(s):\n")
        for i, n in enumerate(names, 1):
            ready = "" if eng.ENGINES[n].available() else f"  {YELLOW}(needs {eng.ENGINES[n].needs}){END}"
            print(f"[{i}] {eng.ENGINES[n].description}{ready}")
        print(f"[{len(names) + 1}] ALL configured engines")
        choice = input(f"\n[+] Select option(s), comma separated (default: {','.join(eng.DEFAULT_ENGINES)}): ").strip()
        if not choice:
            selected = None
        elif choice == str(len(names) + 1):
            selected = "all"
        else:
            selected = []
            for c in choice.split(","):
                c = c.strip()
                if c.isdigit() and 1 <= int(c) <= len(names):
                    selected.append(names[int(c) - 1])
                elif c in names:
                    selected.append(c)
            selected = selected or None

        proxy_in = input("[+] SOCKS5/HTTP proxy (e.g. socks5h://127.0.0.1:9050, 'tor', blank = direct): ").strip()
        try:
            pool = ProxyPool([proxy_in] if proxy_in else ())
        except ProxyError as e:
            err(str(e))
            return 2
        if pool:
            try:
                info(f"Exit IP via proxy: {check(pool.next())['ip']}")
            except Exception as e:  # noqa: BLE001
                err(f"Proxy check failed ({e}); continuing anyway.")

        out = None
        if input("[+] Save the output to a file? (Y/N) ").strip().lower().startswith("y"):
            out = input("[~] File name (.txt/.csv/.json/.jsonl): ").strip() or "dorks-eye-results.txt"
        else:
            print("[!] Saving is skipped...")
        print("\n  " + "»" * 78)

        while True:
            dork = input("\n[+] Enter the dork search query (blank to quit): ").strip()
            if not dork:
                break
            try:
                amount = int(input("[+] Number of results per engine: ").strip() or "10")
            except ValueError:
                err("Please enter a valid number!")
                continue
            counter = 0

            def on_result(r):
                nonlocal counter
                counter += 1
                print_result(counter, r)

            report = eng.search(dork, selected, amount, pool=pool, on_result=on_result, on_status=info)
            if out and report.results:
                out = save(out, dork, report.results)
            info(f"{counter} unique results.")
    except KeyboardInterrupt:
        print(f"\n\n{RED}[!] User interruption detected..!{END}")
    print(f"\n\t\t{BLUE}Dorks Eye{END}\n\t{RED}[!] I like to See Ya, Hacking{END} 😃\n")
    return 0


# --------------------------------------------------------------------------- argparse


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    g = common.add_argument_group("network")
    g.add_argument("-x", "--proxy", action="append", metavar="URL",
                   help="search proxy: socks5h://host:port, socks5://user:pass@host:port, http://..., 'tor'. "
                        "Repeat to rotate. Env: DORKSEYE_PROXY")
    g.add_argument("--proxy-file", metavar="FILE", help="file with one proxy per line (rotated round-robin)")
    g.add_argument("--timeout", type=int, default=15, help="per-request timeout in seconds (default 15)")
    g.add_argument("--delay", type=float, default=2.0, help="seconds between engine requests (default 2)")
    s = common.add_argument_group("search")
    s.add_argument("-e", "--engines", help=f"comma list or 'all' (default {','.join(eng.DEFAULT_ENGINES)})")
    s.add_argument("-n", "--amount", type=int, default=10, help="results per engine (default 10)")
    s.add_argument("-o", "--output", help="save results; format from extension: .txt .csv .json .jsonl")

    p = argparse.ArgumentParser(prog="dorks-eye", description="Multi-engine dork search with SOCKS5 and AI operators.")
    p.add_argument("-V", "--version", action="version", version=f"dorks-eye {__version__}")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("search", parents=[common], help="run one or more dorks")
    sp.add_argument("dork", nargs="*", help="dork query (quote it)")
    sp.add_argument("-f", "--dork-file", help="file with one dork per line")
    sp.add_argument("--retries", type=int, default=1, help="retries per engine, next proxy each time (default 1)")
    sp.add_argument("--json", action="store_true", help="print JSON to stdout (for piping into other tools/AIs)")
    sp.add_argument("-v", "--verbose", action="store_true", help="show titles")
    sp.set_defaults(func=cmd_search)

    from .ai import PROVIDERS

    ap = sub.add_parser("agent", parents=[common], help="let an AI model operate the tool")
    ap.add_argument("objective", nargs="*", help="what you want found, incl. scope (e.g. your domain)")
    ap.add_argument("-p", "--provider", default=os.environ.get("DORKSEYE_PROVIDER", "anthropic"),
                    help=f"one of: {', '.join(PROVIDERS)} (default anthropic, env DORKSEYE_PROVIDER)")
    ap.add_argument("-m", "--model", help="model name (env DORKSEYE_MODEL)")
    ap.add_argument("--base-url", help="custom OpenAI-compatible endpoint (any server/gateway)")
    ap.add_argument("--api-key-env", help="name of env var holding the API key for --base-url")
    ap.add_argument("--llm-proxy", help="proxy for the AI API traffic (separate from search proxy)")
    ap.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], help="Claude effort level")
    ap.add_argument("--max-searches", type=int, default=15, help="cap on searches the AI may run (default 15)")
    ap.add_argument("--max-turns", type=int, default=30, help="cap on model round-trips (default 30)")
    ap.add_argument("-i", "--interactive", action="store_true", help="keep chatting after the first answer")
    ap.add_argument("-q", "--quiet", action="store_true", help="don't log each search")
    ap.set_defaults(func=cmd_agent)

    mp = sub.add_parser("mcp", parents=[common], help="run as an MCP server for any MCP-capable AI client")
    mp.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])
    mp.set_defaults(func=cmd_mcp)

    ep = sub.add_parser("engines", help="list engines and whether they're configured")
    ep.set_defaults(func=cmd_engines)

    cp = sub.add_parser("check-proxy", parents=[common], help="verify proxies and show exit IPs")
    cp.set_defaults(func=cmd_check_proxy)
    return p


def main(argv=None) -> int:
    if sys.version_info < (3, 9):
        print("[x] Dorks Eye needs Python 3.9+")
        return 1
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        return interactive()
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        build_parser().print_help()
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        err("User interruption detected..!")
        return 130


if __name__ == "__main__":
    sys.exit(main())
