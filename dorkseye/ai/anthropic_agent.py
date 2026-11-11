"""Claude (Anthropic API) operator - manual tool-use loop on the official `anthropic` SDK."""

from __future__ import annotations

import os
from typing import Callable, Optional

from .tools import SYSTEM_PROMPT, TOOLS, ToolExecutor

DEFAULT_MODEL = "claude-opus-5-5"
# Models that accept server-side refusal fallbacks (`fallbacks: "default"`).
FALLBACK_MODELS = {"claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicAgent:
    def __init__(
        self,
        executor: ToolExecutor,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        llm_proxy: Optional[str] = None,
        effort: Optional[str] = None,
        max_turns: int = 30,
        on_text: Optional[Callable[[str], None]] = None,
    ):
        try:
            import anthropic
        except ImportError as e:
            raise SystemExit("[!] Install the Anthropic SDK: pip install 'dorks-eye[ai]'  (or pip install anthropic)") from e

        kwargs = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        if llm_proxy:
            kwargs["http_client"] = anthropic.DefaultHttpxClient(proxy=llm_proxy, trust_env=False)
        self.anthropic = anthropic
        self.client = anthropic.Anthropic(**kwargs)
        self.model = model or os.environ.get("DORKSEYE_MODEL") or DEFAULT_MODEL
        self.effort = effort
        self.executor = executor
        self.max_turns = max_turns
        self.on_text = on_text or (lambda s: None)
        self.messages: list = []
        self.tools = [{"name": t["name"], "description": t["description"], "input_schema": t["schema"]} for t in TOOLS]

    def _create(self):
        params = dict(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=self.tools,
            messages=self.messages,
        )
        if self.effort:
            params["output_config"] = {"effort": self.effort}
        if self.model in FALLBACK_MODELS:
            # If a safety classifier declines, the API re-runs the request on a fallback model.
            return self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **params)
        return self.client.messages.create(**params)

    def run(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        final_text = ""
        for _ in range(self.max_turns):
            try:
                response = self._create()
            except self.anthropic.AuthenticationError:
                raise SystemExit("[!] Anthropic authentication failed - set ANTHROPIC_API_KEY")
            except self.anthropic.NotFoundError as e:
                raise SystemExit(f"[!] Model or endpoint not found ({self.model}): {e.message}")
            except self.anthropic.APIStatusError as e:
                raise SystemExit(f"[!] Anthropic API error {e.status_code}: {e.message}")
            except self.anthropic.APIConnectionError as e:
                raise SystemExit(f"[!] Could not reach the Anthropic API: {e}")

            # Keep the full content (tool_use, thinking, fallback blocks) in history.
            self.messages.append({"role": "assistant", "content": response.content})

            text = "".join(b.text for b in response.content if b.type == "text")
            if text:
                final_text = text
                self.on_text(text)

            if response.stop_reason == "refusal":
                details = getattr(response, "stop_details", None)
                why = getattr(details, "explanation", None) or "the request was declined"
                return final_text or f"[!] Model refused: {why}"
            if response.stop_reason == "max_tokens":
                return final_text + "\n[!] Response truncated (max_tokens)."
            if response.stop_reason != "tool_use":
                return final_text

            results = []
            for block in response.content:
                if block.type == "tool_use":
                    out = self.executor.call(block.name, block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
            # All tool results go back in a single user message.
            self.messages.append({"role": "user", "content": results})
        return final_text + "\n[!] Stopped: reached max agent turns."
