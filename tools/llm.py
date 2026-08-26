"""Thin LLM gateway client for research tooling.

Deliberately minimal: stdlib only, no SDK, no retries beyond one backoff.

Scope rule (enforced socially, not technically): this client may help
*process* text you have already gathered. It may not be the source of an
architectural claim. Every claim in a teardown cites a file path + commit SHA
or a doc URL + date read. See README "Evidence rules".

Usage:
    from tools.llm import chat, embed, health
    print(health())
    print(chat("Summarise this changelog", system="Be terse."))
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BASE_URL = "https://freellm.kaapibyte.com/v1"
TIMEOUT = 120


class LLMError(RuntimeError):
    """Gateway returned an error or is not usable."""


def _load_env() -> None:
    """Load .env into os.environ without overwriting existing values."""
    path = REPO_ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _config() -> tuple[str, str]:
    _load_env()
    key = os.environ.get("LLM_API_KEY", "").strip()
    if not key:
        raise LLMError("LLM_API_KEY is not set. Copy .env.example to .env.")
    base = os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
    return base, key


def _post(path: str, payload: dict) -> dict:
    base, key = _config()
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        f"{base}{path}",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    last: Exception | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:400]
            last = LLMError(f"HTTP {exc.code} from {path}: {detail}")
            # 5xx may be transient provider exhaustion; 4xx will not fix itself.
            if exc.code < 500:
                break
        except (urllib.error.URLError, TimeoutError) as exc:
            last = LLMError(f"network error calling {path}: {exc}")
        if attempt == 0:
            time.sleep(2)
    raise last if last else LLMError("unreachable")


def chat(prompt: str, *, system: str | None = None, model: str | None = None,
         max_tokens: int = 2048, temperature: float = 0.2) -> str:
    """Single-turn completion. Returns assistant text."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    data = _post("/chat/completions", {
        "model": model or os.environ.get("LLM_MODEL", "auto"),
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    })
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"unexpected response shape: {json.dumps(data)[:300]}") from exc


def embed(texts: str | list[str], *, model: str | None = None) -> list[list[float]]:
    """Embed one string or a list. Always returns a list of vectors."""
    items = [texts] if isinstance(texts, str) else list(texts)
    data = _post("/embeddings", {
        "model": model or os.environ.get("LLM_EMBED_MODEL", "auto"),
        "input": items,
    })
    try:
        return [row["embedding"] for row in data["data"]]
    except (KeyError, TypeError) as exc:
        raise LLMError(f"unexpected response shape: {json.dumps(data)[:300]}") from exc


def health() -> dict:
    """Probe the gateway. Never raises — returns a report dict.

    Distinguishes three states that matter operationally:
      auth_failed   bad or missing key
      no_providers  key valid, but gateway has no upstream provider keys
      ok            a completion actually came back
    """
    report: dict = {"base_url": None, "auth": None, "chat": None, "embeddings": None}
    try:
        base, _ = _config()
    except LLMError as exc:
        report["auth"] = f"unconfigured: {exc}"
        return report
    report["base_url"] = base

    try:
        chat("Reply with exactly: OK", max_tokens=16)
        report["auth"] = "ok"
        report["chat"] = "ok"
    except LLMError as exc:
        message = str(exc)
        if "no_providers_configured" in message or "no usable key" in message:
            report["auth"] = "ok"
            report["chat"] = "no_providers: gateway has no upstream provider keys"
        elif "HTTP 401" in message or "HTTP 403" in message:
            report["auth"] = "auth_failed"
            report["chat"] = message
        else:
            report["chat"] = message

    try:
        vectors = embed("probe")
        report["embeddings"] = f"ok (dim={len(vectors[0])})"
    except LLMError as exc:
        message = str(exc)
        report["embeddings"] = (
            "no_providers: no usable embedding keys"
            if "no usable keys" in message else message
        )
    return report


if __name__ == "__main__":
    for field, value in health().items():
        print(f"{field:12} {value}")
