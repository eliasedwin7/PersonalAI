from __future__ import annotations

from personalai.services.command_service import parse_app_command


def test_parse_app_command_requires_wake_word_for_loose_phrases():
    assert parse_app_command("tell me about settings") is None

    command = parse_app_command("Nexus open settings")

    assert command is not None
    assert command.action == "open_settings"


def test_parse_app_command_understands_page_navigation_and_custom_wake_word():
    command = parse_app_command("Friday go to knowledge", wake_word="friday")

    assert command is not None
    assert command.action == "select_page"
    assert command.target == "Knowledge"


def test_parse_app_command_can_be_disabled():
    assert parse_app_command("Nexus test microphone", enabled=False) is None


def test_parse_app_command_recognizes_hi_nexus_greeting():
    command = parse_app_command("Hi Nexus")

    assert command is not None
    assert command.action == "voice_greeting"
    assert "I'm here" in command.response


def test_parse_app_command_recognizes_voice_sleep_phrases():
    command = parse_app_command("Goodbye Nexus")

    assert command is not None
    assert command.action == "voice_sleep"
    assert "pause" in command.response

    command = parse_app_command("Friday stop listening", wake_word="friday")
    assert command is not None
    assert command.action == "voice_sleep"
