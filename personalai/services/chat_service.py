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

from personalai.core.config import Config
from personalai.core.conversation import Conversation, ConversationStore
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
}

DEFAULT_TASK = "general"


def system_prompt_for(task: str) -> str:
    return SYSTEM_PROMPTS.get(task, SYSTEM_PROMPTS[DEFAULT_TASK])


@dataclass
class ChatService:
    config: Config
    store: ConversationStore
    client: OllamaClient

    def send(
        self,
        conversation: Conversation,
        user_message: str,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """Append the user's message, call Ollama with the full history,
        append and save the reply. Returns the reply text."""
        conversation.append("user", user_message)
        model = self.config.model_for(conversation.task)
        messages = conversation.as_ollama_messages(system_prompt_for(conversation.task))
        reply = self.client.chat(messages, model, on_token=on_token)
        conversation.append("assistant", reply)
        self.store.save(conversation)
        return reply
