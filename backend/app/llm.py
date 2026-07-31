from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol


class LLMError(RuntimeError):
    pass


class LLMProvider(Protocol):
    def generate(self, prompt: str) -> str: ...


class OllamaProvider:
    def __init__(self, base_url: str, model: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def generate(self, prompt: str) -> str:
        body = json.dumps(
            {"model": self.model, "prompt": prompt, "stream": False, "format": "json"}
        ).encode()
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                payload = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise LLMError(str(exc)) from exc
        return payload.get("response", "")


_provider: LLMProvider | None = None


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        from app.config import get_settings

        settings = get_settings()
        if settings.llm_provider != "ollama":
            raise LLMError(f"Unsupported llm_provider: {settings.llm_provider}")
        _provider = OllamaProvider(settings.llm_base_url, settings.llm_model, settings.llm_timeout)
    return _provider


def configure_provider(provider: LLMProvider) -> None:
    global _provider
    _provider = provider


def reset_provider() -> None:
    global _provider
    _provider = None


def build_prompt(description: str, os_type: str) -> str:
    return (
        "You generate behavior templates for LISA, a cyber-range activity simulator. "
        "A template describes which applications a simulated user runs and when. "
        f"Target OS: {os_type}. "
        "Return ONLY a JSON object with these keys: "
        "applications_used (array of application names as strings), "
        "work_start (HH:MM), work_end (HH:MM), "
        "activities (array of short activity descriptions). "
        "Use realistic applications for the described role and OS. "
        "Do not add any keys beyond those listed. "
        f"Role description: {description}"
    )


def parse_template(raw: str) -> dict | None:
    from pydantic import ValidationError

    from app.schemas import GeneratedTemplate

    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return None
    try:
        return GeneratedTemplate(**obj).model_dump()
    except (ValidationError, TypeError):
        return None
