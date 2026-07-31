from __future__ import annotations

from personalai.core.config import DEFAULT_MODELS, Config, ConfigStore, MemoryEntry


def test_default_config_has_all_tasks():
    config = Config()
    for task in ("general", "story", "code"):
        assert config.model_for(task) == DEFAULT_MODELS[task]
    assert config.airllm_max_new_tokens == 512
    assert config.assistant_memory == ""


def test_model_for_unknown_task_falls_back_to_general():
    config = Config()
    assert config.model_for("nonsense") == config.models["general"]


def test_shared_gpu_profile_keeps_a_deep_model_on_demand():
    config = Config()

    config.apply_local_profile("16gb")

    assert config.model_for("general") == "qwen3:8b"
    assert config.fast_model == "qwen3:4b"
    assert config.deep_model == "qwen3:14b"
    assert config.unload_models_after_reply is True
    assert "qwen3:14b" in config.recommended_local_models()


def test_round_trip(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    config = store.load()
    config.ollama_url = "http://192.168.1.50:11434"
    config.models["story"] = "mixtral"
    config.context_char_limit = 5000
    config.assistant_memory = "Prefers Australian English."
    config.global_hotkey_enabled = True
    config.memory_entries = [MemoryEntry("Prefers concise answers.")]
    store.save(config)

    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded.ollama_url == "http://192.168.1.50:11434"
    assert reloaded.model_for("story") == "mixtral"
    assert reloaded.context_char_limit == 5000
    assert reloaded.assistant_memory == "Prefers Australian English."
    assert reloaded.global_hotkey_enabled is True
    assert reloaded.memory_entries[0].text == "Prefers concise answers."
    assert "Prefers concise answers." in reloaded.memory_context()
    # untouched tasks keep their defaults after a partial models dict is saved
    assert reloaded.model_for("code") == DEFAULT_MODELS["code"]


def test_missing_file_gives_defaults(tmp_path):
    config = ConfigStore(tmp_path / "nope.json").load()
    assert config.ollama_url == "http://127.0.0.1:11434"


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    config = ConfigStore(path).load()
    assert config.ollama_url == "http://127.0.0.1:11434"


def test_unknown_keys_preserved_across_save(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"future_field": 42}', encoding="utf-8")
    store = ConfigStore(path)
    config = store.load()
    store.save(config)
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["future_field"] == 42
