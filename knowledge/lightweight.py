# This file is part of Crystal-Sculpt-Diffus-Coder.
# Crystal-Sculpt-Diffus-Coder is free software: you can redistribute it and/or modify it under the terms of the GNU Affero General Public License as published by the Free Software Foundation, either version 3 of the License, or any later version.
# Crystal-Sculpt-Diffus-Coder is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License along with Crystal-Sculpt-Diffus-Coder.  If not, see <https://www.gnu.org/licenses/>.

"""
Lightweight model client — single shared instance for low-cost operations.

Two responsibilities:
  1. Tool/skill summarization — LLM-driven structured summary extraction
  2. Conversation summarization — replacement for heavy main-model summary
"""

import json
import sys
import threading
from openai import OpenAI

_client = None
_client_lock = threading.Lock()
_config: dict | None = None
_available: bool | None = None  # tri-state: None=unchecked, True/False


def _load_config() -> dict | None:
    """Load lightweight_model section from config.json."""
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
        lm = cfg.get("lightweight_model")
        if lm and lm.get("api_key") and lm.get("model"):
            return lm
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return None


def _get_client() -> OpenAI | None:
    """Lazy singleton: create the lightweight OpenAI client on first call."""
    global _client, _config, _available

    if _available is False:
        return None

    if _client is None:
        with _client_lock:
            if _client is None:
                _config = _load_config()
                if _config is None:
                    _available = False
                    print("[Lightweight] No lightweight_model in config.json — disabled",
                          file=sys.stderr)
                    return None
                try:
                    _client = OpenAI(
                        api_key=_config["api_key"],
                        base_url=_config.get("base_url", ""),
                        timeout=15.0,
                    )
                    _available = True
                    print(f"[Lightweight] Client ready: {_config['model']} "
                          f"@ {_config.get('base_url', 'default')}",
                          file=sys.stderr)
                except Exception as e:
                    _available = False
                    print(f"[Lightweight] Client init failed: {e}", file=sys.stderr)
                    return None
    return _client


def get_model() -> str:
    """Return the lightweight model name, or empty string if unavailable."""
    global _config
    if _config is None:
        _config = _load_config()
    return (_config or {}).get("model", "")


def is_thinking() -> bool:
    """Return whether thinking mode is enabled for the lightweight model."""
    global _config
    if _config is None:
        _config = _load_config()
    return (_config or {}).get("thinking", False)


def _extra_body() -> dict | None:
    """Build extra_body dict for thinking mode, matching main model behavior."""
    if is_thinking():
        return {"thinking": {"type": "enabled"}}
    return {"thinking": {"type": "disabled"}}


def get_temperature() -> float:
    global _config
    if _config is None:
        _config = _load_config()
    return (_config or {}).get("temperature", 0.1)


def get_max_tokens() -> int:
    global _config
    if _config is None:
        _config = _load_config()
    return (_config or {}).get("max_tokens", 600)


def is_available() -> bool:
    """Check if lightweight model is configured and reachable."""
    return _get_client() is not None


SUMMARY_PROMPT = r"""Extract a structured summary from the documentation below. Return ONLY valid JSON, no markdown fences, no commentary.

Required JSON structure:
{
  "title": "<document name or skill name>",
  "summary": "<1-2 sentence description of what this tool/skill does, 40-100 chars, in Chinese>",
  "key_points": ["<key rule or principle>", ...],
  "tags": ["<Chinese keyword>", "<English keyword>", ...]
}

Rules:
- summary: focus on WHEN and WHY to use this, not implementation details
- key_points: 3-5 most important rules, constraints, or triggers. Each under 80 chars.
- tags: 4-6 relevant search keywords in Chinese and English

Document:
"""


def summarize_text(text: str, doc_name: str = "") -> dict | None:
    """Use lightweight LLM to generate a structured summary dict from raw text.

    Returns dict with title, summary, key_points, tags, or None on failure.
    """
    client = _get_client()
    if client is None:
        return None

    model = (_config or {}).get("model", "")
    temperature = (_config or {}).get("temperature", 0.1)
    max_tokens = (_config or {}).get("max_tokens", 600)

    # Truncate text to avoid blowing the prompt
    text_snippet = text[:4000]

    try:
        kwargs = dict(
            model=model,
            messages=[
                {"role": "user", "content": SUMMARY_PROMPT + text_snippet}
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )
        eb = _extra_body()
        if eb:
            kwargs["extra_body"] = eb
        resp = client.chat.completions.create(**kwargs)
        result = resp.choices[0].message.content
        if result:
            result = result.strip()
            # Strip markdown fences if the model wrapped JSON in them
            if result.startswith("```"):
                lines = result.split("\n")
                result = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            data = json.loads(result)
            if doc_name:
                data.setdefault("title", doc_name)
            data.setdefault("memory_id", f"skill:{doc_name}" if doc_name else "")
            print(f"[Lightweight] Summary generated for '{doc_name}' "
                  f"({len(text_snippet)}→{len(json.dumps(data, ensure_ascii=False))} chars)",
                  file=sys.stderr)
            return data
    except json.JSONDecodeError as e:
        print(f"[Lightweight] Summary JSON parse failed for '{doc_name}': {e}",
              file=sys.stderr)
    except Exception as e:
        print(f"[Lightweight] Summarization failed for '{doc_name}': {e}",
              file=sys.stderr)
    return None
