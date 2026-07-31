"""Nexus command-line interface.

    myai chat ["message"] [--task general|story|code] [--session NAME]
              [--context FILE-OR-FOLDER ...] [--reset]
    myai story ["message"] ...      # shortcut for: chat --task story
    myai code ["message"] ...       # shortcut for: chat --task code
    myai caption IMAGE ["instruction"] [--session NAME]
                                     # describe/ask about an image
    myai list                       # saved conversations
    myai show NAME [--full]         # print a conversation's transcript
    myai models                     # models Ollama currently has pulled
    myai export PATH                # ZIP backup of conversations and memory
    myai backends                   # list backends + active one
    myai config show
    myai config set KEY VALUE       # e.g. backend anthropic, models.story llama3.1
    myai gui                        # launch the desktop app
    myai mic-test [--seconds N]     # diagnose "is my mic being picked up at all"
    myai agent [--workspace PATH] [--mode plan|auto|manual] ["task"]
                                     # file-aware assistant, scoped to a folder
    myai image "prompt" [--reference PATH] [--out PATH] [--checkpoint NAME]
                                     # generate an image via Stable Diffusion Forge
    myai image-models                # list checkpoints Forge has available

The chat backend is swappable: Ollama (local, default), Anthropic
(Claude), an OpenAI-compatible API (OpenAI itself, Codex-style
endpoints, or anything else exposing the same wire format - point
config's openai_base_url at it), or AirLLM for experimental in-process
local Hugging Face inference. Switch with `myai config set backend
<name>`; API keys come from the ANTHROPIC_API_KEY / OPENAI_API_KEY
environment variables, never from config - see SETUP.md.

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
from personalai.services.knowledge_service import KnowledgeStore


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
        knowledge_store=KnowledgeStore(),
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
    print(f"Nexus - task '{conversation.task}', session '{conversation.name}'. "
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
    print(f"Nexus - task '{conversation.task}', session '{conversation.name}'. "
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


def cmd_mic_test(args: argparse.Namespace) -> int:
    """Diagnose "is my mic being picked up at all" independent of the
    Voice tab - records a few seconds and prints the actual input
    levels, so a mic/OS-settings problem can be told apart from the
    Voice tab's own silence-detection sensitivity. Also the tool to use
    if the OS's own "default" input device turns out to be silent (a
    real, observed issue on some laptops - see
    voice_service.list_input_devices_detailed()'s docstring): pass
    --device to try a specific index from the list this prints. Nexus's
    Voice workspace always uses the Windows default input device."""
    from personalai.services import voice_service

    if not voice_service.is_recording_available():
        print("[error] The 'sounddevice' package isn't installed: "
              "pip install sounddevice", file=sys.stderr)
        return 1

    devices = voice_service.list_input_devices()
    if devices:
        print("Input devices found:")
        for d in devices:
            print(f"  {d}")
    else:
        print("[warning] Could not list input devices - continuing anyway.")

    device = args.device
    device_note = f"device [{device}]" if device is not None else "the default microphone"
    seconds = args.seconds
    print(f"\nRecording {seconds:g}s from {device_note} - talk normally...")
    try:
        peak, levels = voice_service.mic_level_test(seconds, device=device)
    except PersonalAIError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    print()
    for i, level in enumerate(levels):
        bar = "#" * min(60, int(level / 40))
        print(f"  {i * voice_service.MIC_TEST_WINDOW_S:4.2f}s  {level:7.0f}  {bar}")

    print(f"\nPeak input level: {peak:.0f} (int16 RMS, 0-32767 scale)")
    if peak < 80:
        print(
            "[diagnosis] Levels stayed very low the whole time - this looks like "
            f"{device_note} isn't actually being picked up. Try another device from "
            "the list above with --device N, or check Windows Sound settings > "
            "Input (is the right device selected as default, is it muted, is the "
            "volume/gain turned up).\n"
            "If a device with \"with SST\" in its name (Smart Sound Technology, "
            "common on newer Intel/Realtek laptops) is the only one that ever "
            "showed real levels but has now stopped responding entirely (even "
            "this test fails on it), that's a driver-level lockup outside this "
            "app's control - restarting the \"Windows Audio\" service or "
            "rebooting typically clears it."
        )
    else:
        print(
            "[diagnosis] Real audio is being captured. If the Voice tab still "
            "says \"Didn't hear anything\", its sensitivity may need adjusting "
            "rather than the mic itself."
        )
    return 0


def cmd_agent(args: argparse.Namespace) -> int:
    """File-aware assistant scoped to a workspace folder - see
    services/agent_service.py's module docstring for the tool-calling
    design and the three modes (plan/auto/manual)."""
    from personalai.services.agent_service import Activity, AgentMode, AgentService

    service, config = _build_service()
    workspace_str = args.workspace or config.agent_workspace
    if not workspace_str:
        print("[error] No workspace folder set. Pass --workspace PATH or run: "
              "myai config set agent_workspace PATH", file=sys.stderr)
        return 1
    workspace = Path(workspace_str).expanduser().resolve()
    if not workspace.is_dir():
        print(f"[error] Workspace folder not found: {workspace}", file=sys.stderr)
        return 1

    mode_str = args.mode or config.agent_mode
    try:
        mode = AgentMode(mode_str)
    except ValueError:
        print(f"[error] Unknown mode '{mode_str}' (expected one of: "
              f"{', '.join(config_mod.AGENT_MODE_NAMES)}).", file=sys.stderr)
        return 1

    agent = AgentService(chat_service=service)
    session_name = args.session or "agent"
    conversation = service.store.load_or_create(session_name, DEFAULT_TASK)
    if args.reset:
        conversation = Conversation(name=session_name, task=DEFAULT_TASK)

    def on_activity(activity: Activity) -> None:
        marker = "applied" if activity.applied else "proposed/skipped"
        print(f"\n[{activity.tool} - {marker}] args={activity.args}\n{activity.result}\n")

    def on_confirm(description: str) -> bool:
        print(f"\n[confirm] {description}")
        answer = input("Proceed? [y/N] ").strip().lower()
        return answer in ("y", "yes")

    def run_one(message: str) -> bool:
        try:
            agent.run_turn(
                conversation, message, workspace, mode,
                on_activity=on_activity, on_confirm=on_confirm, on_token=_print_stream_token,
            )
            print()
            return True
        except PersonalAIError as exc:
            print(f"\n[error] {exc}", file=sys.stderr)
            return False

    print(f"Nexus agent - workspace '{workspace}', mode '{mode.value}'.")
    if args.message:
        return 0 if run_one(" ".join(args.message)) else 1

    print("Type 'exit' or Ctrl+D to quit.\n")
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
        run_one(line)
    return 0


def _image_save_dir(config: config_mod.Config) -> Path:
    if config.image_save_dir:
        return Path(config.image_save_dir).expanduser()
    return config_mod.APP_DIR / "images"


def cmd_image(args: argparse.Namespace) -> int:
    """Generate an image from a prompt, or a prompt + a reference image,
    via Stable Diffusion Forge - see services/image_service.py."""
    from personalai.services.image_service import build_forge_client

    config_mod.ensure_dirs()
    config = config_mod.ConfigStore().load()
    client = build_forge_client(config)
    prompt = " ".join(args.prompt)

    try:
        if args.checkpoint:
            client.set_checkpoint(args.checkpoint)
        if args.reference:
            reference_path = Path(args.reference)
            if not reference_path.is_file():
                print(f"[error] Reference image not found: {reference_path}", file=sys.stderr)
                return 1
            image_bytes = client.img2img(
                prompt, reference_path.read_bytes(), steps=args.steps, cfg=args.cfg,
                denoising_strength=args.denoise,
            )
        else:
            image_bytes = client.txt2img(prompt, steps=args.steps, cfg=args.cfg)
    except PersonalAIError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    if args.out:
        out_path = Path(args.out)
    else:
        import datetime
        save_dir = _image_save_dir(config)
        save_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
        out_path = save_dir / f"image_{stamp}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(image_bytes)
    print(f"Saved: {out_path}")
    return 0


def cmd_image_models(args: argparse.Namespace) -> int:
    from personalai.services.image_service import build_forge_client

    config = config_mod.ConfigStore().load()
    client = build_forge_client(config)
    if not client.health():
        print(f"Forge is not reachable at {config.forge_url}.", file=sys.stderr)
        return 1
    checkpoints = client.list_checkpoints()
    if not checkpoints:
        print("No checkpoints found (or Forge didn't return any).")
        return 0
    for name in checkpoints:
        print(name)
    return 0


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


def cmd_export(args: argparse.Namespace) -> int:
    """Create a portable backup of configuration and conversation JSON."""
    from personalai.core.backup import export_backup

    config_mod.ensure_dirs()
    store = config_mod.ConfigStore()
    try:
        saved = export_backup(Path(args.path), store.path, ConversationStore())
    except OSError as exc:
        print(f"[error] Could not write backup: {exc}", file=sys.stderr)
        return 1
    print(f"Backup saved: {saved}")
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
        "airllm": "local in-process Hugging Face model loading (experimental)",
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
    print(f"airllm_max_new_tokens = {config.airllm_max_new_tokens}")
    print(f"context_char_limit  = {config.context_char_limit}")
    print(f"history_char_limit  = {config.history_char_limit}")
    print(f"mic_device          = {'default' if config.mic_device is None else config.mic_device}")
    print(f"whisper_model       = {config.whisper_model}")
    print(f"read_replies_aloud  = {config.read_replies_aloud}")
    print(f"assistant_memory    = {config.assistant_memory or '(not set)'}")
    print(f"global_hotkey      = {'Ctrl+Alt+N' if config.global_hotkey_enabled else '(off)'}")
    print(f"setup_completed    = {config.setup_completed}")
    print(f"local_model_profile = {config.local_model_profile}")
    print(f"intelligent_routing = {config.intelligent_routing}")
    print(f"unload_models_after_reply = {config.unload_models_after_reply}")
    print(f"voice_commands_enabled = {config.voice_commands_enabled}")
    print(f"voice_wake_word    = {config.voice_wake_word}")
    print(f"agent_workspace     = {config.agent_workspace or '(not set)'}")
    print(f"agent_mode          = {config.agent_mode}")
    print(f"forge_url           = {config.forge_url}")
    print(f"image_save_dir      = {config.image_save_dir or '(default: ~/.personalai/images)'}")
    print("models:")
    for task in (*TEXT_TASKS, VISION_TASK):
        print(f"  {task:8s} = {config.model_for(task)}")
    print("system prompts (blank = using the built-in default):")
    for task in (*TEXT_TASKS, VISION_TASK):
        override = config.system_prompts.get(task, "")
        print(f"  {task:8s} = {override or '(default)'}")
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
    elif key == "airllm_max_new_tokens":
        try:
            config.airllm_max_new_tokens = int(value)
        except ValueError:
            print("airllm_max_new_tokens must be a number.", file=sys.stderr)
            return 1
    elif key == "context_char_limit":
        try:
            config.context_char_limit = int(value)
        except ValueError:
            print("context_char_limit must be a number.", file=sys.stderr)
            return 1
    elif key == "history_char_limit":
        try:
            config.history_char_limit = int(value)
        except ValueError:
            print("history_char_limit must be a number.", file=sys.stderr)
            return 1
    elif key == "mic_device":
        if value.lower() in ("default", "none", ""):
            config.mic_device = None
        else:
            try:
                config.mic_device = int(value)
            except ValueError:
                print("mic_device must be a device index (see: myai mic-test) "
                      "or 'default'.", file=sys.stderr)
                return 1
    elif key == "whisper_model":
        from personalai.services.voice_service import WHISPER_MODEL_SIZES
        if value not in WHISPER_MODEL_SIZES:
            print(f"Unknown whisper_model '{value}' (expected one of: "
                  f"{', '.join(WHISPER_MODEL_SIZES)}).", file=sys.stderr)
            return 1
        config.whisper_model = value
    elif key == "assistant_memory":
        config.assistant_memory = value.strip()
    elif key == "global_hotkey_enabled":
        if value.lower() not in ("true", "false"):
            print("global_hotkey_enabled must be 'true' or 'false'.", file=sys.stderr)
            return 1
        config.global_hotkey_enabled = value.lower() == "true"
    elif key == "setup_completed":
        if value.lower() not in ("true", "false"):
            print("setup_completed must be 'true' or 'false'.", file=sys.stderr)
            return 1
        config.setup_completed = value.lower() == "true"
    elif key == "local_model_profile":
        if value not in config_mod.LOCAL_MODEL_PROFILES:
            print(f"Unknown local_model_profile '{value}' (expected one of: "
                  f"{', '.join(config_mod.LOCAL_MODEL_PROFILES)}).", file=sys.stderr)
            return 1
        config.apply_local_profile(value)
        config.setup_completed = True
    elif key == "intelligent_routing":
        if value.lower() not in ("true", "false"):
            print("intelligent_routing must be 'true' or 'false'.", file=sys.stderr)
            return 1
        config.intelligent_routing = value.lower() == "true"
    elif key == "unload_models_after_reply":
        if value.lower() not in ("true", "false"):
            print("unload_models_after_reply must be 'true' or 'false'.", file=sys.stderr)
            return 1
        config.unload_models_after_reply = value.lower() == "true"
    elif key == "voice_commands_enabled":
        if value.lower() not in ("true", "false"):
            print("voice_commands_enabled must be 'true' or 'false'.", file=sys.stderr)
            return 1
        config.voice_commands_enabled = value.lower() == "true"
    elif key == "voice_wake_word":
        config.voice_wake_word = value.strip() or "nexus"
    elif key == "read_replies_aloud":
        if value.lower() not in ("true", "false"):
            print("read_replies_aloud must be 'true' or 'false'.", file=sys.stderr)
            return 1
        config.read_replies_aloud = value.lower() == "true"
    elif key == "agent_workspace":
        resolved = Path(value).expanduser()
        if not resolved.is_dir():
            print(f"agent_workspace must be an existing folder: {resolved}", file=sys.stderr)
            return 1
        config.agent_workspace = str(resolved.resolve())
    elif key == "agent_mode":
        if value not in config_mod.AGENT_MODE_NAMES:
            print(f"Unknown agent_mode '{value}' (expected one of: "
                  f"{', '.join(config_mod.AGENT_MODE_NAMES)}).", file=sys.stderr)
            return 1
        config.agent_mode = value
    elif key == "forge_url":
        config.forge_url = value
    elif key == "image_save_dir":
        config.image_save_dir = value
    elif key.startswith("models."):
        task = key.split(".", 1)[1]
        valid_tasks = (*TEXT_TASKS, VISION_TASK)
        if task not in valid_tasks:
            print(f"Unknown task '{task}' (expected one of: {', '.join(valid_tasks)}).",
                  file=sys.stderr)
            return 1
        config.models[task] = value
    elif key.startswith("prompts."):
        task = key.split(".", 1)[1]
        valid_tasks = (*TEXT_TASKS, VISION_TASK)
        if task not in valid_tasks:
            print(f"Unknown task '{task}' (expected one of: {', '.join(valid_tasks)}).",
                  file=sys.stderr)
            return 1
        if value == "":
            config.system_prompts.pop(task, None)  # empty value = reset to the built-in default
        else:
            config.system_prompts[task] = value
    else:
        print(f"Unknown setting '{key}'. Try: backend, ollama_url, openai_base_url, "
              "airllm_max_new_tokens, context_char_limit, history_char_limit, "
              "mic_device, whisper_model, read_replies_aloud, agent_workspace, "
              "assistant_memory, global_hotkey_enabled, setup_completed, "
              "local_model_profile, intelligent_routing, unload_models_after_reply, "
              "voice_commands_enabled, voice_wake_word, "
              "agent_mode, forge_url, image_save_dir, models.general, models.story, "
              "models.code, models.vision, "
              "prompts.general, prompts.story, prompts.code, prompts.vision "
              "(empty prompts.<task> value resets to the default)", file=sys.stderr)
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

    p_mic_test = sub.add_parser(
        "mic-test", help="diagnose whether your microphone is being picked up at all"
    )
    p_mic_test.add_argument("--seconds", type=float, default=4.0,
                            help="how long to record (default: 4)")
    p_mic_test.add_argument("--device", type=int, default=None,
                            help="try a specific device index instead of "
                                 "config's mic_device / the OS default")
    p_mic_test.set_defaults(func=cmd_mic_test)

    p_agent = sub.add_parser(
        "agent", help="file-aware assistant scoped to a workspace folder"
    )
    p_agent.add_argument("message", nargs="*", help="one-shot task; omit for interactive mode")
    p_agent.add_argument("--workspace", help="folder the agent may read/edit/run commands in "
                                             "(default: config's agent_workspace)")
    p_agent.add_argument("--mode", choices=list(config_mod.AGENT_MODE_NAMES),
                         help="plan (propose only) / auto (no per-call confirmation) / "
                              "manual (confirm every write/edit/command) - "
                              "default: config's agent_mode")
    p_agent.add_argument("--session", help="conversation name (default: 'agent')")
    p_agent.add_argument("--reset", action="store_true",
                         help="start this session's history over")
    p_agent.set_defaults(func=cmd_agent)

    p_image = sub.add_parser(
        "image", help="generate an image from a prompt (or prompt + reference) via Forge"
    )
    p_image.add_argument("prompt", nargs="+", help="what to generate")
    p_image.add_argument("--reference", metavar="PATH",
                         help="reference image - does img2img instead of txt2img")
    p_image.add_argument("--out", metavar="PATH",
                         help="where to save the PNG (default: config's image_save_dir)")
    p_image.add_argument("--checkpoint", help="switch Forge's active model first")
    p_image.add_argument("--steps", type=int, default=20)
    p_image.add_argument("--cfg", type=float, default=7.0)
    p_image.add_argument("--denoise", type=float, default=0.75,
                         help="img2img only - how much to change the reference (0-1)")
    p_image.set_defaults(func=cmd_image)

    p_image_models = sub.add_parser(
        "image-models", help="list checkpoints Forge currently has available"
    )
    p_image_models.set_defaults(func=cmd_image_models)

    p_list = sub.add_parser("list", help="list saved conversations")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="print a conversation's transcript")
    p_show.add_argument("name")
    p_show.set_defaults(func=cmd_show)

    p_models = sub.add_parser("models", help="list models Ollama has pulled")
    p_models.set_defaults(func=cmd_models)

    p_export = sub.add_parser("export", help="write a ZIP backup of conversations and memory")
    p_export.add_argument("path", help="destination ZIP path")
    p_export.set_defaults(func=cmd_export)

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
