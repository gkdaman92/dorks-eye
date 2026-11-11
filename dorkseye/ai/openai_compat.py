"""Operator for any OpenAI-compatible chat-completions endpoint.

That covers OpenAI, local models (Ollama, LM Studio, llama.cpp server, vLLM, LocalAI) and
hosted gateways (OpenRouter, Groq, Gemini, Mistral, DeepSeek, xAI, Together, ...).
The model must support function/tool calling.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

from .tools import SYSTEM_PROMPT, TOOLS, ToolExecutor

# name -> (base_url, api-key env var, fallback key for local servers)
PRESETS: dict[str, tuple[str, Optional[str], Optional[str]]] = {
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", None),
    "ollama": ("http://localhost:11434/v1", None, "ollama"),
    "lmstudio": ("http://localhost:1234/v1", None, "lm-studio"),
    "llamacpp": ("http://localhost:8080/v1", None, "sk-no-key"),
    "vllm": ("http://localhost:8000/v1", None, "sk-no-key"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", None),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", None),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY", None),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY", None),
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY", None),
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY", None),
    "together": ("https://api.together.xyz/v1", "TOGETHER_API_KEY", None),
}


class OpenAICompatAgent:
    def __init__(
        self,
        executor: ToolExecutor,
        provider: str = "openai",
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        api_key_env: Optional[str] = None,
        llm_proxy: Optional[str] = None,
        max_turns: int = 30,
        on_text: Optional[Callable[[str], None]] = None,
    ):
        try:
            import openai
        except ImportError as e:
            raise SystemExit("[!] Install the OpenAI-compatible client: pip install 'dorks-eye[ai]'  (or pip install openai)") from e

        preset_url, preset_env, local_key = PRESETS.get(provider, (None, None, None))
        base_url = base_url or os.environ.get("DORKSEYE_BASE_URL") or preset_url
        if not base_url:
            raise SystemExit(f"[!] Unknown provider '{provider}'. Pass --base-url for a custom endpoint.")
        env = api_key_env or preset_env
        api_key = api_key or (os.environ.get(env) if env else None) or local_key or "sk-no-key"
        if env and api_key == "sk-no-key" and not local_key:
            raise SystemExit(f"[!] Set {env} (or pass --api-key-env) for provider '{provider}'.")

        self.model = model or os.environ.get("DORKSEYE_MODEL")
        if not self.model:
            raise SystemExit(f"[!] Pass --model for provider '{provider}' (e.g. the model name your server exposes).")

        kwargs = {"base_url": base_url, "api_key": api_key}
        if llm_proxy:
            kwargs["http_client"] = openai.DefaultHttpxClient(proxy=llm_proxy, trust_env=False)
        self.openai = openai
        self.client = openai.OpenAI(**kwargs)
        self.provider = provider
        self.executor = executor
        self.max_turns = max_turns
        self.on_text = on_text or (lambda s: None)
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.tools = [
            {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["schema"]}}
            for t in TOOLS
        ]

    def run(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        final_text = ""
        for _ in range(self.max_turns):
            try:
                resp = self.client.chat.completions.create(model=self.model, messages=self.messages, tools=self.tools)
            except self.openai.AuthenticationError:
                raise SystemExit(f"[!] Authentication failed for provider '{self.provider}'")
            except self.openai.APIStatusError as e:
                raise SystemExit(f"[!] {self.provider} API error {e.status_code}: {e.message}")
            except self.openai.APIConnectionError as e:
                raise SystemExit(f"[!] Could not reach {self.provider} at {self.client.base_url}: {e}")

            if not resp.choices:
                return final_text or "[!] Empty response from model."
            msg = resp.choices[0].message
            entry: dict = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"}}
                    for tc in msg.tool_calls
                ]
            self.messages.append(entry)

            if msg.content:
                final_text = msg.content
                self.on_text(msg.content)
            if not msg.tool_calls:
                return final_text

            for tc in msg.tool_calls:
                out = self.executor.call(tc.function.name, tc.function.arguments)
                self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
        return final_text + "\n[!] Stopped: reached max agent turns."
