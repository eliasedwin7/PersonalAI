"""PersonalAI command-line interface.

    myai chat ["message"] [--task general|story|code] [--session NAME]
              [--context FILE-OR-FOLDER ...] [--reset]
    myai story ["message"] ...      # shortcut for: chat --task story
    myai code ["message"] ...       # shortcut for: chat --task code
    myai caption IMAGE ["instruction"] [--session NAME]
                                     # describe/ask about an image
    myai list                       # saved conversations
    myai show NAME [--full]         # print a conversation's transcript
    myai models                     # models Ollama currently has pulled
    myai backends                   # list backends (ollama/anthropic/openai) + active one
    myai config show
    myai config set KEY VALUE       # e.g. backend anthropic, models.story llama3.1
    myai gui                        # launch the desktop app

The chat backend is swappable: Ollama (local, default), Anthropic
(Claude), or an OpenAI-compatible API (OpenAI itself, Codex-style
endpoints, or anything else exposing the same wire format - point
config's openai_base_url at it). Switch with
`myai config set backend <name>`; API keys come from the
ANTHROPIC_API_KEY / OPENAI_API_KEY environment variables, never from
config - see SETUP.md.

With no message, `chat`/`story`/`code` drop into an interactive loop
(type a line, get a reply, Ctrl+D or "exit" to quit) - reading in real
prompts is nicer than quoting a whole paragraph on one command line.
Every reply streams to the terminal as it's generated.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from personalai import __version__
from personalai.core import config as config_mod
from personalai.core.conversation import Conversation, ConversationStore
from personalai.core.errors import PersonalAIError
from personalai.services import context_service, vision_service
from personalai.services.backend_factory import build_llm_client
from personalai.services.chat_service import (
    DEFAULT_TASK,
    TEXT_TASKS,
    VISION_TASK,
    ChatService,
)


def _reconfigure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _build_service() -> tuple[ChatService, config_mod.Config]:
    config_mod.ensure_dirs()
    store = config_mod.ConfigStore()
    config = store.load()
    chat_service = ChatService(
        config=config,
        store=ConversationStore(),
        client=build_llm_client(config),
    )
    return chat_service, config


def _print_stream_token(token: str) -> None:
    print(token, end="", flush=True)


def _run_one_message(service: ChatService, conversation: Conversation, message: str) -> bool:
    """Returns whether the message actually got a reply - callers in
    one-shot mode use this for the process exit code; REPL mode ignores
    it and just keeps the conversation going."""
    try:
        service.send(conversation, message, on_token=_print_stream_token)
        print()  # newline after the streamed reply
        return True
    except PersonalAIError as exc:
        print(f"\n[error] {exc}", file=sys.stderr)
        return False


def _run_repl(service: ChatService, conversation: Conversation) -> None:
    print(f"PersonalAI - task '{conversation.task}', session '{conversation.name}'. "
          "Type 'exit' or Ctrl+D to quit.\n")
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in ("exit", "quit"):
            break
        print("ai> ", end="", flush=True)
        _run_one_message(service, conversation, line)


def cmd_chat(args: argparse.Namespace) -> int:
    service, _config = _build_service()
    # story/code carry a fixed _task; plain "chat" carries --task instead.
    # Read _task first WITHOUT touching .task, which story/code namespaces
    # never have (no --task argument was added for them).
    task = getattr(args, "_task", None) or getattr(args, "task", None) or DEFAULT_TASK
    session_name = args.session or task
    conversation = service.store.load_or_create(session_name, task)
    if conversation.task != task:
        print(f"[note] session '{session_name}' was created for task "
              f"'{conversation.task}'; keeping that task. Use --session "
              "with a new name to start a different one.", file=sys.stderr)

    if args.reset:
        conversation = Conversation(name=session_name, task=conversation.task)

    context_blocks = []
    for context_path in args.context or []:
        try:
            context_blocks.append(
                context_service.load_context_path(Path(context_path), _config.context_char_limit)
            )
        except PersonalAIError as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 1

    if args.message:
        message = context_service.build_user_message(" ".join(args.message), context_blocks)
        return 0 if _run_one_message(service, conversation, message) else 1

    if context_blocks:
        # in REPL mode, context applies to the FIRST message the user types
        first_context = "\n\n".join(context_blocks)
        print(f"[loaded context from {len(context_blocks)} file(s) - will be "
              "prepended to your next message]")
        _run_repl_with_context(service, conversation, first_context)
    else:
        _run_repl(service, conversation)
    return 0


def _run_repl_with_context(service: ChatService, conversation: Conversation,
                           first_context: str) -> None:
    print(f"PersonalAI - task '{conversation.task}', session '{conversation.name}'. "
          "Type 'exit' or Ctrl+D to quit.\n")
    first = True
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in ("exit", "quit"):
            break
        message = context_service.build_user_message(line, [first_context]) if first else line
        first = False
        print("ai> ", end="", flush=True)
        _run_one_message(service, conversation, message)


def cmd_caption(args: argparse.Namespace) -> int:
    service, _config = _build_service()
    image_path = Path(args.image)
    instruction = (" ".join(args.instruction) if args.instruction
                  else vision_service.DEFAULT_INSTRUCTION)
    session_name = args.session or VISION_TASK
    conversation = service.store.load_or_create(session_name, VISION_TASK)
    if args.reset:
        conversation = Conversation(name=session_name, task=VISION_TASK)

    try:
        service.send_with_image(conversation, instruction, image_path,
                                on_token=_print_stream_token)
        print()
        return 0
    except PersonalAIError as exc:
        print(f"\n[error] {exc}", file=sys.stderr)
        return 1


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        from personalai.ui.app import main as gui_main
    except ImportError as exc:
        print(
            "[error] The desktop GUI needs PySide6, which isn't installed.\n"
            "Install it with: pip install PySide6\n"
            f"(underlying error: {exc})", file=sys.stderr,
        )
        return 1
    return gui_main()


def cmd_list(args: argparse.Namespace) -> int:
    config_mod.ensure_dirs()
    store = ConversationStore()
    names = store.list_all()
    if not names:
        print("No saved conversations yet.")
        return 0
    for name in names:
        conv = store.load_or_create(name, DEFAULT_TASK)
        print(f"{name:30s} task={conv.task:8s} messages={len(conv.messages)}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    config_mod.ensure_dirs()
    store = ConversationStore()
    if args.name not in store.list_all():
        print(f"No conversation named '{args.name}'.", file=sys.stderr)
        return 1
    conv = store.load_or_create(args.name, DEFAULT_TASK)
    for msg in conv.messages:
        prefix = {"user": "you", "assistant": "ai", "system": "sys"}.get(msg.role, msg.role)
        print(f"[{msg.timestamp}] {prefix}> {msg.content}\n")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    """Always inspects the local Ollama server specifically - "what's
    pulled" is inherently an Ollama question, regardless of which
    backend is currently active (useful to check before switching back
    to it, or just to see what's on disk)."""
    from personalai.services.ollama_client import OllamaClient

    _service, config = _build_service()
    client = OllamaClient(config.ollama_url)
    if not client.is_available():
        print(f"Ollama is not reachable at {config.ollama_url}.", file=sys.stderr)
        return 1
    models = client.list_models()
    if not models:
        print("No models pulled yet. Try: ollama pull llama3.1")
        return 0
    for name in models:
        tag = " (default)" if name in config.models.values() else ""
        print(f"{name}{tag}")
    return 0


def cmd_backends(args: argparse.Namespace) -> int:
    import os

    config = config_mod.ConfigStore().load()
    notes = {
        "ollama": f"local server at {config.ollama_url}",
        "anthropic": ("via ANTHROPIC_API_KEY" if os.environ.get("ANTHROPIC_API_KEY")
                      else "via ANTHROPIC_API_KEY (not set)"),
        "openai": (f"base_url={config.openai_base_url}"
                   + ("" if os.environ.get("OPENAI_API_KEY")
                      else ", OPENAI_API_KEY not set")),
    }
    for name in config_mod.BACKEND_NAMES:
        marker = "*" if name == config.backend else " "
        print(f"{marker} {name:10s} {notes[name]}")
    print("\n* = active. Switch with: myai config set backend <name>")
    return 0


def cmd_config_show(args: argparse.Namespace) -> int:
    config_mod.ensure_dirs()
    config = config_mod.ConfigStore().load()
    print(f"backend             = {config.backend}")
    print(f"ollama_url          = {config.ollama_url}")
    print(f"openai_base_url     = {config.openai_base_url}")
    print(f"context_char_limit  = {config.context_char_limit}")
    print("models:")
    for task in (*TEXT_TASKS, VISION_TASK):
        print(f"  {task:8s} = {config.model_for(task)}")
    return 0


def cmd_config_set(args: argparse.Namespace) -> int:
    config_mod.ensure_dirs()
    store = config_mod.ConfigStore()
    config = store.load()
    key, value = args.key, args.value
    if key in ("anthropic_api_key", "openai_api_key"):
        env_name = "ANTHROPIC_API_KEY" if key == "anthropic_api_key" else "OPENAI_API_KEY"
        print(f"API keys aren't stored in config - set the {env_name} "
              "environment variable instead (see SETUP.md).", file=sys.stderr)
        return 1
    if key == "backend":
        if value not in config_mod.BACKEND_NAMES:
            print(f"Unknown backend '{value}' (expected one of: "
                  f"{', '.join(config_mod.BACKEND_NAMES)}).", file=sys.stderr)
            return 1
        config.backend = value
    elif key == "ollama_url":
        config.ollama_url = value
    elif key == "openai_base_url":
        config.openai_base_url = value
    elif key == "context_char_limit":
        try:
            config.context_char_limit = int(value)
        except ValueError:
            print("context_char_limit must be a number.", file=sys.stderr)
            return 1
    elif key.startswith("models."):
        task = key.split(".", 1)[1]
        valid_tasks = (*TEXT_TASKS, VISION_TASK)
        if task not in valid_tasks:
            print(f"Unknown task '{task}' (expected one of: {', '.join(valid_tasks)}).",
                  file=sys.stderr)
            return 1
        config.models[task] = value
    else:
        print(f"Unknown setting '{key}'. Try: backend, ollama_url, openai_base_url, "
              "context_char_limit, models.general, models.story, models.code, "
              "models.vision", file=sys.stderr)
        return 1
    store.save(config)
    print(f"{key} = {value}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="myai", description="Your local, offline AI assistant.")
    parser.add_argument("--version", action="version", version=f"myai {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_chat_like(name: str, task: str, help_text: str) -> None:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("message", nargs="*", help="one-shot message; omit for interactive mode")
        p.add_argument("--session", help="conversation name (default: the task name)")
        p.add_argument("--context", action="append", metavar="PATH",
                       help="include a file OR folder as reference material (repeatable)")
        p.add_argument("--reset", action="store_true",
                       help="start this session's history over")
        if name == "chat":
            p.add_argument("--task", default=DEFAULT_TASK, choices=list(TEXT_TASKS),
                           help="which system prompt to use (default: general)")
        p.set_defaults(func=cmd_chat, _task=task if name != "chat" else None)

    add_chat_like("chat", DEFAULT_TASK, "General-purpose chat")
    add_chat_like("story", "story", "Creative writing / story assistant")
    add_chat_like("code", "code", "Coding assistant")

    p_caption = sub.add_parser("caption", help="describe/ask about an image with a vision model")
    p_caption.add_argument("image", help="path to an image file")
    p_caption.add_argument("instruction", nargs="*",
                           help="what to ask about it (default: describe it)")
    p_caption.add_argument("--session", help="conversation name (default: 'vision')")
    p_caption.add_argument("--reset", action="store_true",
                           help="start this session's history over")
    p_caption.set_defaults(func=cmd_caption)

    p_gui = sub.add_parser("gui", help="launch the desktop app")
    p_gui.set_defaults(func=cmd_gui)

    p_list = sub.add_parser("list", help="list saved conversations")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="print a conversation's transcript")
    p_show.add_argument("name")
    p_show.set_defaults(func=cmd_show)

    p_models = sub.add_parser("models", help="list models Ollama has pulled")
    p_models.set_defaults(func=cmd_models)

    p_backends = sub.add_parser("backends", help="list backends and which one is active")
    p_backends.set_defaults(func=cmd_backends)

    p_config = sub.add_parser("config", help="view or change settings")
    config_sub = p_config.add_subparsers(dest="config_command", required=True)
    p_config_show = config_sub.add_parser("show")
    p_config_show.set_defaults(func=cmd_config_show)
    p_config_set = config_sub.add_parser("set")
    p_config_set.add_argument("key")
    p_config_set.add_argument("value")
    p_config_set.set_defaults(func=cmd_config_set)

    return parser


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except PersonalAIError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
