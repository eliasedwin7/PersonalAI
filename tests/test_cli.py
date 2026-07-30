"""End-to-end CLI tests: real argument parsing + real file storage
(isolated to a tmp home), with OllamaClient's network calls mocked at the
class level so nothing needs a live Ollama server."""

from __future__ import annotations

import pytest

from personalai import cli
from personalai.core.conversation import ConversationStore
from personalai.core.errors import OllamaUnavailable
from personalai.services.ollama_client import OllamaClient


@pytest.fixture(autouse=True)
def _fake_ollama(monkeypatch):
    """Every test gets a working, canned Ollama by default; individual
    tests override .chat/.is_available for other scenarios."""
    monkeypatch.setattr(OllamaClient, "chat",
                        lambda self, messages, model, on_token=None, images=None:
                        (on_token("canned reply") if on_token else None) or "canned reply")
    monkeypatch.setattr(OllamaClient, "is_available", lambda self: True)
    monkeypatch.setattr(OllamaClient, "list_models", lambda self: ["llama3.1", "qwen2.5-coder"])


def test_chat_one_shot_saves_conversation(isolated_home, capsys):
    exit_code = cli.main(["chat", "hello", "there"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "canned reply" in out

    conv = ConversationStore().load_or_create("general", "general")
    assert len(conv.messages) == 2
    assert conv.messages[0].content == "hello there"


def test_story_uses_story_task_and_default_session_name(isolated_home):
    cli.main(["story", "continue the scene"])
    conv = ConversationStore().load_or_create("story", "story")
    assert conv.task == "story"
    assert len(conv.messages) == 2


def test_code_uses_code_task(isolated_home):
    cli.main(["code", "write fizzbuzz"])
    conv = ConversationStore().load_or_create("code", "code")
    assert conv.task == "code"


def test_custom_session_name(isolated_home):
    cli.main(["story", "--session", "dune-chapter2", "keep going"])
    names = ConversationStore().list_all()
    assert "dune-chapter2" in names
    assert "story" not in names  # didn't fall back to the default session


def test_reset_clears_history(isolated_home):
    cli.main(["chat", "first message"])
    cli.main(["chat", "--reset", "second message"])
    conv = ConversationStore().load_or_create("general", "general")
    # reset wipes prior history, so only this turn's two messages remain
    assert len(conv.messages) == 2
    assert conv.messages[0].content == "second message"


def test_list_and_show(isolated_home, capsys):
    cli.main(["story", "hello"])
    capsys.readouterr()

    cli.main(["list"])
    out = capsys.readouterr().out
    assert "story" in out
    assert "messages=2" in out

    cli.main(["show", "story"])
    out = capsys.readouterr().out
    assert "hello" in out
    assert "canned reply" in out


def test_show_unknown_conversation_errors(isolated_home, capsys):
    exit_code = cli.main(["show", "does-not-exist"])
    assert exit_code == 1
    assert "No conversation" in capsys.readouterr().err


def test_models_lists_pulled_models(isolated_home, capsys):
    exit_code = cli.main(["models"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "llama3.1" in out
    assert "qwen2.5-coder" in out


def test_models_reports_when_ollama_unreachable(isolated_home, monkeypatch, capsys):
    monkeypatch.setattr(OllamaClient, "is_available", lambda self: False)
    exit_code = cli.main(["models"])
    assert exit_code == 1
    assert "not reachable" in capsys.readouterr().err


def test_config_show_and_set_round_trip(isolated_home, capsys):
    cli.main(["config", "set", "models.story", "mixtral"])
    capsys.readouterr()
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert "story    = mixtral" in out


def test_config_set_rejects_unknown_key(isolated_home, capsys):
    exit_code = cli.main(["config", "set", "nonsense", "value"])
    assert exit_code == 1
    assert "Unknown setting" in capsys.readouterr().err


def test_config_set_rejects_unknown_task(isolated_home, capsys):
    exit_code = cli.main(["config", "set", "models.painting", "some-model"])
    assert exit_code == 1
    assert "Unknown task" in capsys.readouterr().err


def test_config_show_includes_backend(isolated_home, capsys):
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert "backend             = ollama" in out


def test_config_set_backend_switches_it(isolated_home, capsys):
    cli.main(["config", "set", "backend", "anthropic"])
    capsys.readouterr()
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert "backend             = anthropic" in out


def test_config_set_backend_rejects_unknown(isolated_home, capsys):
    exit_code = cli.main(["config", "set", "backend", "nonsense"])
    assert exit_code == 1
    assert "Unknown backend" in capsys.readouterr().err


def test_config_set_refuses_api_key_and_points_at_env_var(isolated_home, capsys):
    exit_code = cli.main(["config", "set", "anthropic_api_key", "sk-ant-whatever"])
    assert exit_code == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_config_set_openai_base_url(isolated_home, capsys):
    cli.main(["config", "set", "openai_base_url", "https://my-proxy.example/v1"])
    capsys.readouterr()
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert "https://my-proxy.example/v1" in out


def test_config_set_airllm_max_new_tokens(isolated_home, capsys):
    cli.main(["config", "set", "airllm_max_new_tokens", "256"])
    capsys.readouterr()
    cli.main(["config", "show"])
    assert "airllm_max_new_tokens = 256" in capsys.readouterr().out


def test_config_set_airllm_max_new_tokens_rejects_non_number(isolated_home, capsys):
    exit_code = cli.main(["config", "set", "airllm_max_new_tokens", "many"])
    assert exit_code == 1
    assert "must be a number" in capsys.readouterr().err


def test_config_show_includes_voice_settings(isolated_home, capsys):
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert "mic_device          = default" in out
    assert "whisper_model       = base.en" in out
    assert "read_replies_aloud  = True" in out


def test_config_set_mic_device(isolated_home, capsys):
    cli.main(["config", "set", "mic_device", "15"])
    capsys.readouterr()
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert "mic_device          = 15" in out


def test_config_set_mic_device_back_to_default(isolated_home, capsys):
    cli.main(["config", "set", "mic_device", "15"])
    capsys.readouterr()
    cli.main(["config", "set", "mic_device", "default"])
    capsys.readouterr()
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert "mic_device          = default" in out


def test_config_set_mic_device_rejects_non_integer(isolated_home, capsys):
    exit_code = cli.main(["config", "set", "mic_device", "not-a-number"])
    assert exit_code == 1
    assert "device index" in capsys.readouterr().err


def test_config_set_whisper_model(isolated_home, capsys):
    cli.main(["config", "set", "whisper_model", "small.en"])
    capsys.readouterr()
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert "whisper_model       = small.en" in out


def test_config_set_whisper_model_rejects_unknown(isolated_home, capsys):
    exit_code = cli.main(["config", "set", "whisper_model", "huge"])
    assert exit_code == 1
    assert "Unknown whisper_model" in capsys.readouterr().err


def test_config_set_read_replies_aloud(isolated_home, capsys):
    cli.main(["config", "set", "read_replies_aloud", "true"])
    capsys.readouterr()
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert "read_replies_aloud  = True" in out


def test_config_set_read_replies_aloud_rejects_invalid(isolated_home, capsys):
    exit_code = cli.main(["config", "set", "read_replies_aloud", "maybe"])
    assert exit_code == 1
    assert "must be" in capsys.readouterr().err


def test_backends_command_lists_all_three_and_marks_active(isolated_home, capsys):
    exit_code = cli.main(["backends"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "ollama" in out and "anthropic" in out and "openai" in out and "airllm" in out
    assert "* ollama" in out  # default backend marked active


def test_backends_command_reflects_switch(isolated_home, capsys):
    cli.main(["config", "set", "backend", "openai"])
    capsys.readouterr()
    cli.main(["backends"])
    out = capsys.readouterr().out
    assert "* openai" in out
    assert "* ollama" not in out


def test_switching_backend_actually_changes_which_client_chat_uses(
    isolated_home, monkeypatch, capsys
):
    """End-to-end proof (not just the factory unit test): once backend is
    switched to anthropic, `myai chat` must hit the Anthropic path - not
    silently keep using the mocked Ollama client from the autouse fixture."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cli.main(["config", "set", "backend", "anthropic"])
    capsys.readouterr()

    exit_code = cli.main(["chat", "hello"])
    assert exit_code == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_context_file_is_prepended_to_one_shot_message(isolated_home, tmp_path):
    outline = tmp_path / "STORY_OUTLINE.md"
    outline.write_text("Chapter 3: the siege begins.", encoding="utf-8")
    cli.main(["story", "--context", str(outline), "continue this"])

    conv = ConversationStore().load_or_create("story", "story")
    sent_message = conv.messages[0].content
    assert "the siege begins" in sent_message
    assert sent_message.endswith("continue this")


def test_context_file_missing_reports_error(isolated_home, capsys):
    exit_code = cli.main(["story", "--context", "nope.md", "continue"])
    assert exit_code == 1
    assert "not found" in capsys.readouterr().err


def test_context_folder_is_prepended_to_one_shot_message(isolated_home, tmp_path):
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "ch1.md").write_text("Chapter 1: the arrival.", encoding="utf-8")
    (chapters / "ch2.md").write_text("Chapter 2: the siege begins.", encoding="utf-8")

    cli.main(["story", "--context", str(chapters), "continue this"])

    conv = ConversationStore().load_or_create("story", "story")
    sent_message = conv.messages[0].content
    assert "the arrival" in sent_message
    assert "the siege begins" in sent_message
    assert sent_message.endswith("continue this")


def test_ollama_unreachable_reports_error_not_traceback(isolated_home, monkeypatch, capsys):
    def raise_unavailable(self, messages, model, on_token=None):
        raise OllamaUnavailable("Cannot reach Ollama at http://127.0.0.1:11434: refused")

    monkeypatch.setattr(OllamaClient, "chat", raise_unavailable)
    exit_code = cli.main(["chat", "hello"])
    assert exit_code == 1  # a failed one-shot message must not report success
    assert "Cannot reach Ollama" in capsys.readouterr().err


def test_repl_mode_reads_lines_until_exit(isolated_home, monkeypatch, capsys):
    lines = iter(["hi there", "exit"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(lines))
    exit_code = cli.main(["chat"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "canned reply" in out

    conv = ConversationStore().load_or_create("general", "general")
    assert conv.messages[0].content == "hi there"


def test_repl_mode_handles_ctrl_d(isolated_home, monkeypatch):
    def raise_eof(_prompt):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)
    exit_code = cli.main(["chat"])
    assert exit_code == 0
    assert ConversationStore().list_all() == []  # nothing was ever sent


def test_caption_describes_image(isolated_home, tmp_path, capsys):
    image = tmp_path / "cat.png"
    image.write_bytes(b"fake bytes")
    exit_code = cli.main(["caption", str(image), "what is in this picture?"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "canned reply" in out

    conv = ConversationStore().load_or_create("vision", "vision")
    assert "cat.png" in conv.messages[0].content
    assert "what is in this picture?" in conv.messages[0].content


def test_caption_default_instruction_when_none_given(isolated_home, tmp_path):
    from personalai.services import vision_service

    image = tmp_path / "dog.png"
    image.write_bytes(b"fake bytes")
    cli.main(["caption", str(image)])

    conv = ConversationStore().load_or_create("vision", "vision")
    assert vision_service.DEFAULT_INSTRUCTION in conv.messages[0].content


def test_caption_missing_image_reports_error(isolated_home, capsys):
    exit_code = cli.main(["caption", "nope.png"])
    assert exit_code == 1
    assert "not found" in capsys.readouterr().err


def test_caption_custom_session(isolated_home, tmp_path):
    image = tmp_path / "cat.png"
    image.write_bytes(b"fake bytes")
    cli.main(["caption", str(image), "--session", "my-photos"])
    assert "my-photos" in ConversationStore().list_all()
    assert "vision" not in ConversationStore().list_all()


def test_mic_test_reports_error_when_sounddevice_missing(isolated_home, monkeypatch, capsys):
    from personalai.services import voice_service

    monkeypatch.setattr(voice_service, "is_recording_available", lambda: False)
    exit_code = cli.main(["mic-test"])
    assert exit_code == 1
    assert "sounddevice" in capsys.readouterr().err


def test_mic_test_diagnoses_low_levels_as_mic_problem(isolated_home, monkeypatch, capsys):
    from personalai.services import voice_service

    monkeypatch.setattr(voice_service, "is_recording_available", lambda: True)
    monkeypatch.setattr(voice_service, "list_input_devices",
                        lambda: ["[0] Fake Mic (default)"])
    monkeypatch.setattr(voice_service, "mic_level_test",
                        lambda seconds, device=None: (5.0, [5.0, 3.0]))

    exit_code = cli.main(["mic-test", "--seconds", "1"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Fake Mic" in out
    assert "isn't actually being picked up" in out


def test_mic_test_diagnoses_good_levels(isolated_home, monkeypatch, capsys):
    from personalai.services import voice_service

    monkeypatch.setattr(voice_service, "is_recording_available", lambda: True)
    monkeypatch.setattr(voice_service, "list_input_devices", list)
    monkeypatch.setattr(voice_service, "mic_level_test",
                        lambda seconds, device=None: (900.0, [900.0]))

    exit_code = cli.main(["mic-test"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Real audio is being captured" in out


def test_mic_test_uses_explicit_device_flag_over_config(isolated_home, monkeypatch, capsys):
    from personalai.services import voice_service

    cli.main(["config", "set", "mic_device", "5"])
    capsys.readouterr()

    monkeypatch.setattr(voice_service, "is_recording_available", lambda: True)
    monkeypatch.setattr(voice_service, "list_input_devices", list)
    seen = {}

    def fake_mic_level_test(seconds, device=None):
        seen["device"] = device
        return (900.0, [900.0])

    monkeypatch.setattr(voice_service, "mic_level_test", fake_mic_level_test)

    exit_code = cli.main(["mic-test", "--device", "9"])
    assert exit_code == 0
    assert seen["device"] == 9  # --device wins over the configured mic_device (5)


def test_mic_test_falls_back_to_configured_device(isolated_home, monkeypatch, capsys):
    from personalai.services import voice_service

    cli.main(["config", "set", "mic_device", "5"])
    capsys.readouterr()

    monkeypatch.setattr(voice_service, "is_recording_available", lambda: True)
    monkeypatch.setattr(voice_service, "list_input_devices", list)
    seen = {}

    def fake_mic_level_test(seconds, device=None):
        seen["device"] = device
        return (900.0, [900.0])

    monkeypatch.setattr(voice_service, "mic_level_test", fake_mic_level_test)

    exit_code = cli.main(["mic-test"])
    assert exit_code == 0
    assert seen["device"] == 5


def test_config_show_includes_agent_and_image_settings(isolated_home, capsys):
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert "agent_workspace     = (not set)" in out
    assert "agent_mode          = plan" in out
    assert "forge_url           = http://127.0.0.1:7860" in out


def test_config_set_agent_workspace_requires_existing_folder(isolated_home, tmp_path, capsys):
    exit_code = cli.main(["config", "set", "agent_workspace", str(tmp_path / "nope")])
    assert exit_code == 1
    assert "existing folder" in capsys.readouterr().err

    exit_code = cli.main(["config", "set", "agent_workspace", str(tmp_path)])
    assert exit_code == 0
    cli.main(["config", "show"])
    assert str(tmp_path.resolve()) in capsys.readouterr().out


def test_config_set_agent_mode_rejects_unknown(isolated_home, capsys):
    exit_code = cli.main(["config", "set", "agent_mode", "yolo"])
    assert exit_code == 1
    assert "Unknown agent_mode" in capsys.readouterr().err


def test_config_set_agent_mode_accepts_known_values(isolated_home, capsys):
    exit_code = cli.main(["config", "set", "agent_mode", "auto"])
    assert exit_code == 0
    cli.main(["config", "show"])
    assert "agent_mode          = auto" in capsys.readouterr().out


def test_config_set_forge_url(isolated_home, capsys):
    cli.main(["config", "set", "forge_url", "http://192.168.1.50:7860"])
    capsys.readouterr()
    cli.main(["config", "show"])
    assert "forge_url           = http://192.168.1.50:7860" in capsys.readouterr().out


def test_config_show_includes_default_system_prompts(isolated_home, capsys):
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert "story    = (default)" in out


def test_config_set_prompts_story_overrides_it(isolated_home, capsys):
    cli.main(["config", "set", "prompts.story", "Always write in second person."])
    capsys.readouterr()
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert "story    = Always write in second person." in out


def test_config_set_prompts_unknown_task_rejected(isolated_home, capsys):
    exit_code = cli.main(["config", "set", "prompts.nonsense", "whatever"])
    assert exit_code == 1
    assert "Unknown task" in capsys.readouterr().err


def test_config_set_prompts_empty_value_resets_to_default(isolated_home, capsys):
    cli.main(["config", "set", "prompts.story", "Always write in second person."])
    capsys.readouterr()
    cli.main(["config", "set", "prompts.story", ""])
    capsys.readouterr()
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert "story    = (default)" in out


def test_config_show_includes_history_char_limit(isolated_home, capsys):
    cli.main(["config", "show"])
    out = capsys.readouterr().out
    assert "history_char_limit  = 24000" in out


def test_config_set_history_char_limit(isolated_home, capsys):
    cli.main(["config", "set", "history_char_limit", "5000"])
    capsys.readouterr()
    cli.main(["config", "show"])
    assert "history_char_limit  = 5000" in capsys.readouterr().out


def test_config_set_history_char_limit_rejects_non_number(isolated_home, capsys):
    exit_code = cli.main(["config", "set", "history_char_limit", "not-a-number"])
    assert exit_code == 1
    assert "must be a number" in capsys.readouterr().err


def test_agent_command_reports_missing_workspace(isolated_home, capsys):
    exit_code = cli.main(["agent", "do something"])
    assert exit_code == 1
    assert "No workspace folder set" in capsys.readouterr().err


def test_agent_command_reports_missing_workspace_folder(isolated_home, tmp_path, capsys):
    exit_code = cli.main(["agent", "--workspace", str(tmp_path / "nope"), "do something"])
    assert exit_code == 1
    assert "Workspace folder not found" in capsys.readouterr().err


def test_agent_command_one_shot_plan_mode(isolated_home, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(OllamaClient, "chat",
                        lambda self, messages, model, on_token=None, images=None:
                        (on_token("just a plain reply") if on_token else None)
                        or "just a plain reply")
    workspace = tmp_path / "ws"
    workspace.mkdir()

    exit_code = cli.main(["agent", "--workspace", str(workspace), "--mode", "plan", "hello"])
    assert exit_code == 0
    assert "just a plain reply" in capsys.readouterr().out


def test_image_command_saves_generated_png(isolated_home, tmp_path, monkeypatch, capsys):
    from personalai.services import image_service

    fake_png = b"\x89PNG fake bytes"
    monkeypatch.setattr(image_service.ForgeClient, "txt2img",
                        lambda self, prompt, **kw: fake_png)

    out_path = tmp_path / "out.png"
    exit_code = cli.main(["image", "a red circle", "--out", str(out_path)])
    assert exit_code == 0
    assert out_path.read_bytes() == fake_png
    assert "Saved" in capsys.readouterr().out


def test_image_command_uses_reference_for_img2img(monkeypatch, isolated_home, tmp_path, capsys):
    from personalai.services import image_service

    fake_png = b"\x89PNG fake bytes"
    seen = {}

    def fake_img2img(self, prompt, reference_image, **kw):
        seen["reference"] = reference_image
        seen["kwargs"] = kw
        return fake_png

    monkeypatch.setattr(image_service.ForgeClient, "img2img", fake_img2img)

    reference = tmp_path / "ref.png"
    reference.write_bytes(b"reference bytes")
    out_path = tmp_path / "out.png"

    exit_code = cli.main(["image", "make it blue", "--reference", str(reference),
                          "--out", str(out_path), "--denoise", "0.3"])
    assert exit_code == 0
    assert seen["reference"] == b"reference bytes"
    assert seen["kwargs"]["denoising_strength"] == 0.3
    assert out_path.read_bytes() == fake_png


def test_image_command_missing_reference_reports_error(isolated_home, tmp_path, capsys):
    exit_code = cli.main(["image", "a prompt", "--reference", str(tmp_path / "nope.png")])
    assert exit_code == 1
    assert "not found" in capsys.readouterr().err


def test_image_models_command_lists_checkpoints(isolated_home, monkeypatch, capsys):
    from personalai.services import image_service

    monkeypatch.setattr(image_service.ForgeClient, "health", lambda self: True)
    monkeypatch.setattr(image_service.ForgeClient, "list_checkpoints",
                        lambda self: ["model_a.safetensors", "model_b.safetensors"])

    exit_code = cli.main(["image-models"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "model_a.safetensors" in out
    assert "model_b.safetensors" in out


def test_image_models_command_reports_when_forge_unreachable(isolated_home, monkeypatch, capsys):
    from personalai.services import image_service

    monkeypatch.setattr(image_service.ForgeClient, "health", lambda self: False)
    exit_code = cli.main(["image-models"])
    assert exit_code == 1
    assert "not reachable" in capsys.readouterr().err


def test_gui_command_reports_missing_pyside_cleanly(isolated_home, monkeypatch, capsys):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "personalai.ui.app" or name.startswith("PySide6"):
            raise ImportError("No module named 'PySide6'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    exit_code = cli.main(["gui"])
    assert exit_code == 1
    assert "PySide6" in capsys.readouterr().err
