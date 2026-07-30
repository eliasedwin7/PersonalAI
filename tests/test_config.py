from __future__ import annotations

from personalai.core.config import DEFAULT_MODELS, Config, ConfigStore


def test_default_config_has_all_tasks():
    config = Config()
    for task in ("general", "story", "code"):
        assert config.model_for(task) == DEFAULT_MODELS[task]


def test_model_for_unknown_task_falls_back_to_general():
    config = Config()
    assert config.model_for("nonsense") == config.models["general"]


def test_round_trip(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    config = store.load()
    config.ollama_url = "http://192.168.1.50:11434"
    config.models["story"] = "mixtral"
    config.context_char_limit = 5000
    store.save(config)

    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded.ollama_url == "http://192.168.1.50:11434"
    assert reloaded.model_for("story") == "mixtral"
    assert reloaded.context_char_limit == 5000
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
