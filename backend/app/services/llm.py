"""Anthropic call + strict JSON validation with retry on malformed output."""
import json
import re
from pathlib import Path
from typing import Callable, Optional

import jsonschema

from ..config import settings

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
Caller = Callable[[str, list], str]


class ExtractionError(RuntimeError):
    pass


def load_prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


def load_schema(name: str) -> dict:
    return json.loads(load_prompt(name))


def anthropic_call(system: str, messages: list) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    resp = client.messages.create(
        model=settings.anthropic_model, max_tokens=4096, temperature=0,
        system=system, messages=messages,
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def parse_json_text(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in reply")
    return json.loads(text[start:end + 1])


def complete_json(system: str, user: str, schema: dict, *,
                  caller: Optional[Caller] = None, max_retries: int = 2) -> dict:
    caller = caller or anthropic_call
    messages = [{"role": "user", "content": user}]
    last: Exception = ValueError("no attempts")
    for _ in range(max_retries + 1):
        text = caller(system, messages)
        try:
            data = parse_json_text(text)
            jsonschema.validate(data, schema)
            return data
        except (ValueError, jsonschema.ValidationError) as e:
            last = e
            messages += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"That reply was invalid ({str(e)[:300]}). "
                                            "Return ONLY the corrected JSON object."},
            ]
    raise ExtractionError(f"Model returned invalid JSON after {max_retries + 1} attempts: {last}")
