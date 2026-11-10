"""Client for a local OpenAI-compatible vLLM server (Qwen3.5 on a cluster GPU). Nothing leaves the cluster.

Thinking is disabled (chat_template_kwargs.enable_thinking = false) and JSON output is requested, as in
src/scripts/vllm_termpop/catalogue_ner.py. Responses are parsed as JSON; failures are retried, then recorded.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request


class LocalLLM:
    def __init__(self, cfg: dict, max_tokens: int | None = None):
        llm = cfg["local_llm"]
        self.host = os.environ.get("LLM_HOST", llm["host"]).rstrip("/")
        self.model = os.environ.get("LLM_MODEL", llm["model"])
        self.temperature = llm["temperature"]
        self.max_tokens = max_tokens or llm["max_tokens"]
        self.timeout = llm["timeout_s"]
        self.retries = llm["max_retries"]

    def served_model(self) -> str:
        with urllib.request.urlopen(self.host + "/v1/models", timeout=30) as r:
            return json.loads(r.read())["data"][0]["id"]

    def chat_json(self, system: str, user: str) -> dict:
        body = json.dumps({
            "model": self.model, "temperature": self.temperature, "max_tokens": self.max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_object"},
        }).encode()
        last = None
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(self.host + "/v1/chat/completions", data=body,
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    out = json.loads(r.read())
                ch = out["choices"][0]
                if ch.get("finish_reason") == "length":
                    raise ValueError("truncated (finish_reason=length)")
                return {"parsed": parse_json(ch["message"]["content"]), "raw": ch["message"]["content"],
                        "usage": out.get("usage", {}), "attempts": attempt + 1}
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as e:
                last = repr(e)
                time.sleep(min(60, 2 ** attempt))
        return {"parsed": None, "raw": None, "error": last, "attempts": self.retries + 1}


def parse_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise
