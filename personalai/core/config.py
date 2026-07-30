"""Per-machine settings: which Ollama server to use, and which model
handles each task. Stored as JSON at ~/.personalai/config.json so it's
easy to hand-edit and never accidentally lives inside a git repo.

Task-based model mapping is the whole point of the "story/code/general"
split: Ollama serves whichever model is currently requested, so switching
task just means picking a different model name - no separate servers,
no restart.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

APP_DIR = Path(os.environ.get("PERSONALAI_HOME", "")) if os.environ.get("PERSONALAI_HOME") \
    else Path.home() / ".personalai"
CONVERSATIONS_DIR = APP_DIR / "conversations"
CONFIG_FILE = APP_DIR / "config.json"

DEFAULT_MODELS = {
    "general": "llama3.1",
    "story": "llama3.1",
    "code": "qwen2.5-coder",
    "vision": "llava",  # image captioning/description, see services/vision_service.py
}


def ensure_dirs() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Config:
    ollama_url: str = "http://127.0.0.1:11434"
    models: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MODELS))
    context_char_limit: int = 12000  # rough guard on --context file size, see context_service.py

    def model_for(self, task: str) -> str:
        return self.models.get(task) or self.models.get("general", DEFAULT_MODELS["general"])


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or CONFIG_FILE
        self._extra: dict = {}  # unknown keys preserved across save, like CharacterStudio's settings

    def load(self) -> Config:
        if not self.path.exists():
            return Config()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return Config()
        known = {f.name for f in fields(Config)}
        self._extra = {k: v for k, v in raw.items() if k not in known}
        kwargs = {k: v for k, v in raw.items() if k in known}
        if "models" in kwargs:
            merged = dict(DEFAULT_MODELS)
            merged.update(kwargs["models"])
            kwargs["models"] = merged
        return Config(**kwargs)

    def save(self, config: Config) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {**self._extra, **asdict(config)}
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
