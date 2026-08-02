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


def build_plugin_prompt(name: str, os_type: str, description: str | None = None) -> str:
    hint = f" Extra context: {description}." if description else ""
    return (
        "You generate application plugins for LISA, a cyber-range activity simulator. "
        "A plugin describes how a simulated user installs, opens and uses one application. "
        f"Target application: {name}. Target OS: {os_type}.{hint} "
        "Return ONLY a JSON object with these keys: "
        "app_info (name, display_name, category), "
        "installation (check_command, install_method, install_commands array, "
        "post_install_commands array, dependencies array), "
        "execution (open_command, close_command, window_class, startup_delay seconds), "
        "activities (array of objects with id, name, weight, min_duration, max_duration, "
        "and commands array), "
        "settings (usage_probability, work_hours_only). "
        "Each command object has type set to one of key, key_combination or type_text, "
        "a delay in seconds, and then key for key, keys for key_combination, "
        "or text for type_text. "
        "The id fields are strings. Commands are keyboard actions performed with xdotool, "
        "never shell commands. Follow this example exactly: "
        '{"app_info": {"name": "slack", "display_name": "Slack", "category": "communication"}, '
        '"installation": {"check_command": "slack --version", "install_method": "apt", '
        '"install_commands": ["sudo apt-get install -y slack"], "post_install_commands": [], '
        '"dependencies": ["xdotool"]}, '
        '"execution": {"open_command": "slack", "close_command": "pkill -f slack", '
        '"window_class": "Slack", "startup_delay": 5}, '
        '"activities": [{"id": "read_messages", "name": "Read messages", "weight": 60, '
        '"min_duration": 20, "max_duration": 90, "commands": ['
        '{"type": "key", "key": "Down", "delay": 1}, '
        '{"type": "key_combination", "keys": "ctrl+k", "delay": 2}]}, '
        '{"id": "reply", "name": "Reply", "weight": 40, "min_duration": 15, "max_duration": 45, '
        '"commands": [{"type": "type_text", "text": "on it", "delay": 1}, '
        '{"type": "key", "key": "Return", "delay": 1}]}], '
        '"settings": {"usage_probability": 0.8, "work_hours_only": true}}. '
        "Give between two and five realistic activities. "
        "Every weight must be above zero and they should sum to about 100. "
        "Do not add keys beyond those in the example."
    )


def parse_plugin(raw: str) -> dict | None:
    from pydantic import ValidationError

    from app.schemas import ApplicationPlugin

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
        plugin = ApplicationPlugin(**obj)
    except (ValidationError, TypeError):
        return None
    usable = [a for a in plugin.activities if a.weight > 0]
    if not usable:
        return None
    plugin.activities = sorted(usable, key=lambda a: a.weight, reverse=True)[:6]
    return plugin.model_dump(exclude_none=True)


def generate_plugin(
    name: str, os_type: str, description: str | None = None, attempts: int = 3
) -> dict | None:
    prompt = build_plugin_prompt(name, os_type, description)
    for _ in range(max(1, attempts)):
        try:
            raw = get_provider().generate(prompt)
        except LLMError:
            return None
        plugin = parse_plugin(raw)
        if plugin is not None:
            return plugin
    return None
