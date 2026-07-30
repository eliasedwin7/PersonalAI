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


class OllamaUnavailable(PersonalAIError):
    """Ollama isn't reachable, or rejected a request."""
