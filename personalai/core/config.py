"""Per-machine settings: which LLM backend and server/API to use, and
which model handles each task. Stored as JSON at ~/.personalai/config.json
so it's easy to hand-edit and never accidentally lives inside a git repo.

Task-based model mapping is the whole point of the "story/code/general"
split: whichever backend is active serves whichever model is currently
requested, so switching task just means picking a different model name -
no separate servers, no restart. `models` stays a flat task->name dict
regardless of backend; a model NAME's meaning depends on which backend
is active (e.g. models.story might be "llama3.1" under Ollama or
"claude-sonnet-5" under Anthropic) - see services/backend_factory.py.

Deliberately NOT stored here: API keys. Those come from the
ANTHROPIC_API_KEY / OPENAI_API_KEY environment variables only, the same
place any other credential belongs - never in a config file that could
be copied, backed up, or accidentally shared.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
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


BACKEND_NAMES = ("ollama", "anthropic", "openai", "airllm")
AGENT_MODE_NAMES = ("plan", "auto", "manual")  # see services/agent_service.py's AgentMode


@dataclass
class MemoryEntry:
    """One approved fact, with enough provenance to review it later."""

    text: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    source: str = "Approved from chat"


@dataclass
class Config:
    backend: str = "ollama"       # "ollama" | "anthropic" | "openai" | "airllm"
                                      # see BACKEND_NAMES
    ollama_url: str = "http://127.0.0.1:11434"
    openai_base_url: str = "https://api.openai.com/v1"  # override for Codex-compatible
                                                          # endpoints, OpenRouter, a local
                                                          # server, etc.
    airllm_max_new_tokens: int = 512  # AirLLM does local in-process generation; this caps
                                        # each reply because it cannot rely on a server-side
                                        # default like Ollama/OpenAI/Claude do.
    models: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MODELS))
    context_char_limit: int = 12000  # rough guard on --context file size, see context_service.py
    history_char_limit: int = 24000  # rough guard on how much conversation HISTORY gets sent
                                       # per turn (oldest turns dropped first past this) - a
                                       # long-running session would otherwise resend its entire
                                       # transcript forever and eventually exceed the model's
                                       # real context window; see Conversation.as_ollama_messages
    mic_device: int | None = None    # legacy value retained so existing config files load;
                                       # Nexus now always uses the OS default input device
    whisper_model: str = "base.en"   # voice input model size, see services/voice_service.py
    read_replies_aloud: bool = True   # Voice tab's "speak replies aloud" checkbox default -
                                       # on by default since talking back is the point of that
                                       # tab; uncheck it there to use voice input as dictation only
    window_geometry: str = ""        # base64 QByteArray from saveGeometry() - GUI only,
                                       # not QSettings/registry, so it lives in this same
                                       # human-readable config.json like everything else
    agent_workspace: str | None = None  # folder Agent mode is allowed to touch - see
                                          # services/agent_service.py's sandboxing
    agent_mode: str = "plan"         # "plan" | "auto" | "manual" - see AGENT_MODE_NAMES.
                                       # Defaults to the safest mode (nothing ever written
                                       # or executed) rather than opting into risk by default.
    forge_url: str = "http://127.0.0.1:7860"  # Stable Diffusion Forge (AUTOMATIC1111-style)
                                                # API - see services/image_service.py
    image_save_dir: str = ""         # where generated images get saved; "" = APP_DIR/images
                                       # (resolved lazily so PERSONALAI_HOME overrides still work)
    assistant_memory: str = ""       # user-approved facts/preferences injected into every
                                       # conversation; editable in Settings, never inferred or
                                       # sent anywhere other than the configured LLM backend
    memory_entries: list[MemoryEntry] = field(default_factory=list)  # individually approved facts
    global_hotkey_enabled: bool = False  # Windows only: Ctrl+Alt+N shows Nexus from the tray
    system_prompts: dict[str, str] = field(default_factory=dict)  # task -> override text;
                                       # a task absent here just uses chat_service.SYSTEM_PROMPTS'
                                       # built-in default, so this dict stays empty until someone
                                       # actually customizes a prompt (see Settings' prompt editor)

    def model_for(self, task: str) -> str:
        return self.models.get(task) or self.models.get("general", DEFAULT_MODELS["general"])

    def memory_context(self) -> str:
        """Combine old free-form notes with individually approved facts."""
        sections = [self.assistant_memory.strip()] if self.assistant_memory.strip() else []
        entries = [f"- {entry.text}" for entry in self.memory_entries if entry.text.strip()]
        if entries:
            sections.append("\n".join(entries))
        return "\n".join(sections)


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
        if "memory_entries" in kwargs:
            kwargs["memory_entries"] = [
                MemoryEntry(**entry) for entry in kwargs["memory_entries"]
                if isinstance(entry, dict) and entry.get("text", "").strip()
            ]
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
