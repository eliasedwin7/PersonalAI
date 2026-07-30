"""AirLLM-backed local inference client.

AirLLM is intentionally optional: it is useful when you want to run a
much larger Hugging Face model than your VRAM would normally allow, but
it brings heavyweight ML dependencies and model downloads. Keeping all
imports inside AirLLMClient means the normal Ollama/Claude/OpenAI paths
stay light and reliable when AirLLM is not installed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from personalai.core.errors import BackendUnavailable, UserFacingError


class AirLLMClient:
    def __init__(self, max_new_tokens: int = 512) -> None:
        self.max_new_tokens = max_new_tokens
        self._models: dict[str, Any] = {}

    def is_available(self) -> bool:
        try:
            import airllm  # noqa: F401
            import torch  # noqa: F401
        except ImportError:
            return False
        return True

    def chat(
        self,
        messages: list[dict],
        model: str,
        on_token: Callable[[str], None] | None = None,
        images: list[str] | None = None,
    ) -> str:
        if images:
            raise UserFacingError(
                "The AirLLM backend does not support image messages. "
                "Use Ollama/OpenAI/Anthropic with a vision-capable model for captions."
            )
        loaded = self._load_model(model)
        prompt = self._format_messages(loaded.tokenizer, messages)
        input_tokens = loaded.tokenizer(
            [prompt],
            return_tensors="pt",
            return_attention_mask=False,
            truncation=True,
            padding=False,
        )
        input_ids = self._to_device(input_tokens["input_ids"])
        try:
            output = loaded.generate(
                input_ids,
                max_new_tokens=self.max_new_tokens,
                use_cache=True,
                return_dict_in_generate=True,
            )
        except Exception as exc:
            raise UserFacingError(f"AirLLM generation failed for model '{model}': {exc}") from exc

        sequence = output.sequences[0]
        new_tokens = sequence[input_ids.shape[-1]:]
        reply = loaded.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
        if on_token and reply:
            on_token(reply)
        return reply

    def _load_model(self, model: str):
        if model in self._models:
            return self._models[model]
        try:
            from airllm import AutoModel
        except ImportError as exc:
            raise BackendUnavailable(
                "AirLLM is not installed in this Python environment. Install the optional "
                "dependencies with: pip install airllm torch transformers accelerate"
            ) from exc
        try:
            loaded = AutoModel.from_pretrained(model)
        except Exception as exc:
            raise UserFacingError(
                f"Could not load AirLLM model '{model}'. Use a Hugging Face repo ID "
                "or local model path, and make sure there is enough disk space for "
                f"AirLLM's layer-shard cache. Underlying error: {exc}"
            ) from exc
        self._models[model] = loaded
        return loaded

    @staticmethod
    def _format_messages(tokenizer, messages: list[dict]) -> str:
        if hasattr(tokenizer, "apply_chat_template"):
            try:
                return tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=True,
                )
            except (AttributeError, RuntimeError, TypeError, ValueError):
                pass
        rendered = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            rendered.append(f"{role}: {content}")
        rendered.append("assistant:")
        return "\n\n".join(rendered)

    @staticmethod
    def _to_device(input_ids):
        try:
            import torch
        except ImportError:
            return input_ids
        if torch.cuda.is_available() and hasattr(input_ids, "cuda"):
            return input_ids.cuda()
        return input_ids
