"""Local voice/app commands that should not go through the LLM."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppCommand:
    action: str
    target: str = ""
    response: str = "Done."


PAGE_ALIASES = {
    "chat": "Chat",
    "voice": "Voice",
    "knowledge": "Knowledge",
    "memory": "Knowledge",
    "images": "Images",
    "image": "Images",
    "agent": "Agent",
    "system": "System",
    "benchmark": "System",
}


def parse_app_command(
    text: str,
    wake_word: str = "nexus",
    enabled: bool = True,
) -> AppCommand | None:
    if not enabled:
        return None
    command = " ".join(text.casefold().strip().split())
    if not command:
        return None
    wake = wake_word.casefold().strip()
    greetings = {
        f"hi {wake}",
        f"hey {wake}",
        f"hello {wake}",
        wake,
    } if wake else set()
    if command in greetings:
        return AppCommand(
            "voice_greeting",
            response="Hi. I'm here. What would you like to work on?",
        )
    sleep_phrases = {
        "stop listening",
        "pause listening",
        "go quiet",
        "sleep",
        "goodbye",
        "bye",
    }
    if wake:
        sleep_phrases.update({
            f"{wake} stop listening",
            f"{wake} pause listening",
            f"goodbye {wake}",
            f"bye {wake}",
        })
    if command in sleep_phrases:
        return AppCommand("voice_sleep", response="Okay. I'll pause here.")
    if wake and command.startswith(wake):
        command = command[len(wake):].strip(" ,")
    elif not command.startswith(("open ", "go to ", "switch to ", "show ", "test ")):
        return None

    if command in {"stop listening", "pause listening", "go quiet", "sleep", "goodbye", "bye"}:
        return AppCommand("voice_sleep", response="Okay. I'll pause here.")
    if command in {"settings", "open settings", "show settings"}:
        return AppCommand("open_settings", response="Opening Settings.")
    if command in {"new chat", "start new chat", "open new chat"}:
        return AppCommand("new_chat", response="Starting a new chat.")
    if command in {"test microphone", "mic test", "test mic"}:
        return AppCommand("test_microphone", response="Testing the microphone.")

    for prefix in ("open ", "go to ", "switch to ", "show "):
        if command.startswith(prefix):
            target = command[len(prefix):].strip()
            page = PAGE_ALIASES.get(target)
            if page:
                return AppCommand("select_page", page, f"Opening {page}.")
    page = PAGE_ALIASES.get(command)
    if page:
        return AppCommand("select_page", page, f"Opening {page}.")
    return None
