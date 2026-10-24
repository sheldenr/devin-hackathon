"""Ollama client helpers: JSON-mode chat, model selection, availability checks."""
import json
import os

import ollama

DEFAULT_MODEL = os.environ.get("OVERTURN_MODEL", "llama3.2:3b")
HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def _client() -> ollama.Client:
    return ollama.Client(host=HOST)


def is_available() -> bool:
    try:
        _client().list()
        return True
    except Exception:
        return False


def list_models() -> list[str]:
    try:
        return [m.model for m in _client().list().models]
    except Exception:
        return []


def chat(prompt: str, system: str = "", model: str = DEFAULT_MODEL) -> str:
    resp = _client().chat(
        model=model,
        messages=(
            [{"role": "system", "content": system}] if system else []
        )
        + [{"role": "user", "content": prompt}],
        options={"temperature": 0.1},
        keep_alive="30m",
    )
    return resp.message.content


def chat_json(prompt: str, system: str = "", model: str = DEFAULT_MODEL) -> dict:
    """Chat with format='json'; returns parsed dict. Retries once on bad JSON."""
    client = _client()
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    last_err = None
    for attempt in range(2):
        resp = client.chat(
            model=model,
            messages=messages,
            format="json",
            options={"temperature": 0.1},
            keep_alive="30m",
        )
        try:
            return json.loads(resp.message.content)
        except json.JSONDecodeError as e:
            last_err = e
            messages.append({"role": "assistant", "content": resp.message.content})
            messages.append(
                {
                    "role": "user",
                    "content": "That was not valid JSON. Reply with only the corrected JSON object.",
                }
            )
    raise ValueError(f"LLM returned malformed JSON twice: {last_err}")


def warmup(model: str = DEFAULT_MODEL) -> None:
    """Load the model into memory so the first real request is fast."""
    _client().generate(model=model, prompt="ok", keep_alive="30m")
