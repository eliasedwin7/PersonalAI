"""Chat orchestration: picks the right system prompt for a task, sends
the full conversation history to Ollama, appends both turns, and saves.

Deliberately thin - it's a few lines of glue between ConversationStore
and OllamaClient. The interesting behavior (task prompts) lives in one
place so `myai story` and `myai code` are just this with a different
task name, not separate code paths.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from personalai.core.config import Config
from personalai.core.conversation import Conversation, ConversationStore
from personalai.core.errors import GenerationCancelled, PersonalAIError, UserFacingError
from personalai.services import vision_service
from personalai.services.knowledge_service import KnowledgeStore
from personalai.services.memory_service import MEMORY_SUGGESTION_PROMPT, parse_suggestions
from personalai.services.ollama_client import OllamaClient

SYSTEM_PROMPTS = {
    "general": (
        "You are a helpful, direct personal assistant running entirely "
        "locally on the user's own machine. Be concise unless asked for "
        "detail."
    ),
    "story": (
        "You are a creative writing collaborator helping the user draft "
        "fiction, dialogue, and worldbuilding. Match the tone and voice "
        "already established in any reference material they give you. "
        "Prefer showing over telling, keep dialogue natural, and ask a "
        "clarifying question if the direction genuinely is ambiguous "
        "rather than guessing wildly."
    ),
    "code": (
        "You are a senior software engineer pair-programming with the "
        "user, running entirely offline. Give runnable, correct code with "
        "minimal surrounding commentary. State assumptions explicitly "
        "when the request is ambiguous rather than guessing silently. "
        "Prefer the standard library and the user's existing stack over "
        "introducing new dependencies unless asked."
    ),
    "vision": (
        "You are an image description assistant. Describe images "
        "accurately and concisely - key subjects, actions, setting, and "
        "any notable details. If asked a specific question about the "
        "image, answer that question directly using only what is "
        "actually visible; say so if something can't be determined from "
        "the image."
    ),
}

# The tasks reachable through plain `myai chat --task ...` - "vision"
# needs an image and lives behind `myai caption` instead, so it's kept
# out of this list to avoid a confusing `--task vision` with no image.
TEXT_TASKS = ("general", "story", "code")

DEFAULT_TASK = "general"
VISION_TASK = "vision"


def system_prompt_for(
    task: str,
    overrides: dict[str, str] | None = None,
    assistant_memory: str = "",
    knowledge_context: str = "",
    deep_thinking: bool = False,
) -> str:
    """`overrides` is Config.system_prompts - a user-edited prompt for a
    task takes priority over the built-in default; a task absent (or
    blank) there just falls through to SYSTEM_PROMPTS as before."""
    prompt = (overrides or {}).get(task) or SYSTEM_PROMPTS.get(task, SYSTEM_PROMPTS[DEFAULT_TASK])
    memory = assistant_memory.strip()
    if memory:
        prompt += f"\n\nUser-approved personal context:\n{memory}"
    if knowledge_context:
        prompt += f"\n\nRelevant local knowledge (use it as evidence and name the source when useful):\n{knowledge_context}"
    if deep_thinking:
        prompt += "\n\nWork through the request carefully before answering. Check assumptions and give a clear final answer without exposing private scratch work."
    return prompt


@dataclass
class ChatService:
    config: Config
    store: ConversationStore
    client: OllamaClient
    knowledge_store: KnowledgeStore | None = None

    def _knowledge_context(self, query: str) -> str:
        if not self.config.knowledge_enabled or self.knowledge_store is None:
            return ""
        embed_query = None
        if isinstance(self.client, OllamaClient):
            embed_query = lambda texts: self.client.embed(texts, self.config.embedding_model)
        try:
            chunks = self.knowledge_store.search(
                query, limit=self.config.knowledge_result_count, embed_query=embed_query,
            )
        except PersonalAIError:
            chunks = self.knowledge_store.search(query, limit=self.config.knowledge_result_count)
        return "\n\n".join(f"[{chunk.source}]\n{chunk.text}" for chunk in chunks)

    def _model_for(self, task: str, message: str, deep_thinking: bool) -> str:
        if deep_thinking:
            return self.config.deep_model or self.config.model_for(task)
        if task != "general" or not self.config.intelligent_routing:
            return self.config.model_for(task)
        if self.config.fast_model and _looks_simple(message):
            return self.config.fast_model
        return self.config.model_for(task)

    def send(
        self,
        conversation: Conversation,
        user_message: str,
        on_token: Callable[[str], None] | None = None,
        deep_thinking: bool = False,
    ) -> str:
        """Append the user's message, call Ollama with the full history,
        append and save the reply. Returns the reply text."""
        conversation.append("user", user_message)
        model = self._model_for(conversation.task, user_message, deep_thinking)
        messages = conversation.as_ollama_messages(
            system_prompt_for(
                conversation.task, self.config.system_prompts, self.config.memory_context(),
                self._knowledge_context(user_message), deep_thinking,
            ),
            char_limit=self.config.history_char_limit)
        try:
            reply = self.client.chat(messages, model, on_token=on_token)
        except GenerationCancelled:
            self.store.save(conversation)
            raise
        conversation.append("assistant", reply)
        self.store.save(conversation)
        return reply

    def suggest_memory(self, conversation: Conversation) -> list[str]:
        """Ask the configured model for facts to review; never persists them itself."""
        if not conversation.messages:
            return []
        transcript = "\n".join(
            f"{message.role}: {message.content}" for message in conversation.messages[-12:]
        )
        response = self.client.chat(
            [
                {"role": "system", "content": MEMORY_SUGGESTION_PROMPT},
                {"role": "user", "content": transcript[-12_000:]},
            ],
            self.config.model_for("general"),
        )
        return parse_suggestions(response)

    def send_with_image(
        self,
        conversation: Conversation,
        instruction: str,
        image_path: Path,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """Like send(), but attaches an image for a vision model. Only a
        readable text note (not the image bytes) is persisted to the
        conversation's JSON file - the actual base64 image is sent to
        Ollama for this request only, never written to disk by us."""
        image_b64 = vision_service.encode_image_base64(image_path)
        note = f"[image: {image_path.name}] {instruction}".strip()
        conversation.append("user", note)
        model = self.config.model_for(conversation.task)
        messages = conversation.as_ollama_messages(
            system_prompt_for(
                conversation.task, self.config.system_prompts, self.config.memory_context(),
                self._knowledge_context(instruction),
            ),
            char_limit=self.config.history_char_limit)
        try:
            reply = self.client.chat(messages, model, on_token=on_token, images=[image_b64])
        except GenerationCancelled:
            self.store.save(conversation)
            raise
        conversation.append("assistant", reply)
        self.store.save(conversation)
        return reply

    def discard_last_reply(self, conversation: Conversation) -> None:
        """Remove the latest text-only assistant reply before regenerating it.

        Image turns cannot be regenerated because the image bytes are intentionally
        never persisted in conversation JSON, so resending would silently change
        what the model sees.
        """
        if len(conversation.messages) < 2:
            raise UserFacingError("There is no reply to regenerate yet.")
        reply, request = conversation.messages[-1], conversation.messages[-2]
        if reply.role != "assistant" or request.role != "user":
            raise UserFacingError("Only the latest assistant reply can be regenerated.")
        if request.content.startswith("[image:"):
            raise UserFacingError("Image replies cannot be regenerated after the image is cleared.")
        conversation.messages.pop()
        self.store.save(conversation)

    def regenerate(
        self,
        conversation: Conversation,
        on_token: Callable[[str], None] | None = None,
        deep_thinking: bool = False,
    ) -> str:
        """Generate a fresh reply to the already-saved final user message."""
        if not conversation.messages or conversation.messages[-1].role != "user":
            raise UserFacingError("There is no user message ready to regenerate.")
        request = conversation.messages[-1].content
        model = self._model_for(conversation.task, request, deep_thinking)
        messages = conversation.as_ollama_messages(
            system_prompt_for(
                conversation.task, self.config.system_prompts, self.config.memory_context(),
                self._knowledge_context(request), deep_thinking,
            ),
            char_limit=self.config.history_char_limit,
        )
        reply = self.client.chat(messages, model, on_token=on_token)
        conversation.append("assistant", reply)
        self.store.save(conversation)
        return reply


def _looks_simple(message: str) -> bool:
    """Keep greetings and lightweight factual requests snappy on the compact model."""
    lower = message.casefold()
    deep_terms = ("plan", "compare", "analyse", "analyze", "debug", "design", "why", "prove", "step by step")
    return len(message) < 220 and not any(term in lower for term in deep_terms)
