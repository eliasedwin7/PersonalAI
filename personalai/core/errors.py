"""Typed exceptions. UserFacingError.message is safe to print verbatim to
the terminal; anything else should be shown with a generic wrapper."""

from __future__ import annotations


class PersonalAIError(Exception):
    """Base for every error this app raises deliberately."""


class UserFacingError(PersonalAIError):
    """An error whose message is written for the user, safe to print as-is."""

    @property
    def message(self) -> str:
        return str(self)


class GenerationCancelled(PersonalAIError):
    """A streamed generation was deliberately stopped by the user."""


class BackendUnavailable(PersonalAIError):
    """The active LLM backend (Ollama, Claude, or an OpenAI-compatible
    API) isn't reachable, or isn't configured (e.g. missing API key)."""


class OllamaUnavailable(BackendUnavailable):
    """Ollama specifically isn't reachable. Kept as its own subclass so
    call sites that want Ollama-specific messaging ("is it installed and
    running?") can still catch it distinctly, while generic code (CLI
    error printing, the GUI status light) can catch BackendUnavailable
    and work the same way regardless of which backend is active."""
