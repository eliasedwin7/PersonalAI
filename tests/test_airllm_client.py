from __future__ import annotations

from typing import ClassVar

import pytest

from personalai.core.errors import UserFacingError
from personalai.services.airllm_client import AirLLMClient


class FakeInputIds:
    shape = (1, 3)


class FakeSequence:
    def __getitem__(self, key):
        assert key == slice(3, None, None)
        return "new-token-ids"


class FakeOutput:
    sequences: ClassVar = [FakeSequence()]


class FakeTokenizer:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
        assert tokenize is False
        assert add_generation_prompt is True
        return "templated prompt"

    def __call__(self, prompts, **kwargs):
        self.prompts.extend(prompts)
        return {"input_ids": FakeInputIds()}

    def decode(self, tokens, skip_special_tokens=True):
        assert tokens == "new-token-ids"
        assert skip_special_tokens is True
        return " generated reply "


class FakeModel:
    def __init__(self) -> None:
        self.tokenizer = FakeTokenizer()
        self.seen = {}

    def generate(self, input_ids, **kwargs):
        self.seen["input_ids"] = input_ids
        self.seen["kwargs"] = kwargs
        return FakeOutput()


def test_airllm_client_generates_with_cached_model_and_streams_once():
    client = AirLLMClient(max_new_tokens=42)
    model = FakeModel()
    client._models["local/model"] = model
    seen = []

    reply = client.chat(
        [{"role": "user", "content": "hello"}],
        "local/model",
        on_token=seen.append,
    )

    assert reply == "generated reply"
    assert seen == ["generated reply"]
    assert model.tokenizer.prompts == ["templated prompt"]
    assert model.seen["kwargs"]["max_new_tokens"] == 42
    assert model.seen["kwargs"]["return_dict_in_generate"] is True


def test_airllm_client_rejects_images():
    client = AirLLMClient()

    with pytest.raises(UserFacingError, match="does not support image"):
        client.chat([{"role": "user", "content": "describe"}], "local/model", images=["abc"])


def test_airllm_falls_back_to_plain_prompt_when_chat_template_fails():
    class PlainTokenizer(FakeTokenizer):
        def apply_chat_template(self, *args, **kwargs):
            raise RuntimeError("no template")

    model = FakeModel()
    model.tokenizer = PlainTokenizer()
    client = AirLLMClient()
    client._models["local/model"] = model

    client.chat(
        [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hello"},
        ],
        "local/model",
    )

    assert model.tokenizer.prompts == ["system: be brief\n\nuser: hello\n\nassistant:"]
