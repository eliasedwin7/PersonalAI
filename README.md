# PersonalAI

**Your own AI assistant - runs fully offline against a local Ollama model
by default, or swap in Claude / OpenAI (or any OpenAI-compatible /
Codex-style API) with one config change.**

A tool that gives you four ready-to-use modes, from the command line or
a small desktop app:

- **`myai chat`** — general-purpose assistant
- **`myai story`** — creative writing / dialogue / worldbuilding collaborator
- **`myai code`** — coding help
- **`myai caption`** — describe or ask questions about an image, using a
  vision-capable model

Every conversation is saved to a plain JSON file on your disk, so you can
pick up where you left off, list past sessions, or hand a transcript to
someone else. With the default Ollama backend, nothing ever leaves your
machine; switching to Claude or OpenAI is an explicit, one-line opt-in
(see [Choosing a backend](#choosing-a-backend) below).

New here? **→ Start with [SETUP.md](SETUP.md)** for installing Ollama and
PersonalAI and having your first conversation.

## Why a CLI, and why three modes instead of one

Different tasks want different models and different instructions. A
model tuned for creative writing shouldn't get the same system prompt as
one being asked to write code — and if you're on a single GPU, you often
want to swap which model is loaded depending on what you're doing anyway.
PersonalAI keeps that switch as simple as typing `story` instead of
`code`; the underlying model for each mode is just a setting you can
change any time (`myai config set models.code deepseek-coder-v2`).

The CLI comes first because it's genuinely useful on its own — a
terminal chat with history, file-context injection, and per-task models
covers a lot of ground with very little code to trust, and it's the
right tool for one-shot or scripted/automated use. The desktop GUI
(`myai gui`, or a real standalone `.exe` — see
[Building a standalone .exe](SETUP.md#building-a-standalone-exe)) is
meant to be the everyday, dependable way to actually *use* PersonalAI —
multi-line input, voice in/out, a colored transcript, session
management, all a window on top of the exact same
`ChatService`/`ConversationStore` the CLI uses, so a session started
with `myai story` shows up there too, and vice versa.

## Quick start

```powershell
# 1. Install Ollama once: https://ollama.com, then pull a model
ollama pull llama3.1

# 2. Install PersonalAI (from an Anaconda Prompt, in this folder)
powershell -ExecutionPolicy Bypass -File Install-PersonalAI-Env.ps1 -Dev

# 3. Chat
conda run -n personalai myai chat "what can you help me with?"
```

See **[SETUP.md](SETUP.md)** for the full walkthrough, including using
this to help with an entirely separate project (like pulling in a file
from another folder as reference material).

## Usage reference

```
myai chat ["message"]              general assistant
myai story ["message"]             creative writing assistant
myai code ["message"]              coding assistant

  --session NAME     name this conversation thread (default: the task name,
                      e.g. all untitled story chats share one "story" thread)
  --context PATH      include a file OR a whole folder as reference material
                      (repeatable; a folder's text files are combined)
  --reset             start this session's history over

myai caption IMAGE ["instruction"]  describe/ask about an image
  --session NAME     name this conversation thread (default: "vision")
  --reset             start this session's history over

myai list                          list every saved conversation
myai show NAME                     print a conversation's full transcript
myai models                        list models Ollama currently has pulled
myai backends                      list backends (ollama/anthropic/openai) + which is active

myai config show                   view current settings
myai config set KEY VALUE          e.g. backend anthropic
                                    e.g. models.story llama3.1
                                    e.g. models.vision llama3.2-vision
                                    e.g. ollama_url http://192.168.1.50:11434
                                    e.g. openai_base_url https://my-proxy.example/v1
                                    e.g. whisper_model small.en
                                    e.g. read_replies_aloud true

myai gui                           launch the desktop app (see also:
                                    Run-PersonalAI-GUI.bat, or build a
                                    real .exe - Build-PersonalAI-Exe.ps1)
myai mic-test [--seconds N]        diagnose whether your mic is being
                                    picked up at all (independent of the
                                    Voice tab's own detection)
```

Run any command with no message (`myai story`) to drop into an
interactive back-and-forth instead of a single question; type `exit` or
press Ctrl+D to leave.

### Example: getting help with something in another project

```powershell
myai story --context "C:\path\to\STORY_OUTLINE.md" "continue chapter 3 where Kellan confronts his brother"
myai code --context ".\my_script.py" "why does this throw a KeyError on line 40?"

# --context also accepts a whole FOLDER - every text file inside (recursively)
# gets combined, each under its own filename header
myai story --context "C:\path\to\chapters" "continue where chapter 5 left off"
```

`--context` just reads the file (or folder) and hands its content to the
model alongside your message — PersonalAI doesn't need to live inside a
project to help with it. A folder is capped at 50 files and the combined
text is truncated the same way a single file is (keeping the end), so it
shares `context_char_limit` rather than needing its own setting.

### Example: describing an image

```powershell
myai caption "C:\path\to\render.png" "does this look like a bedroom or a garden?"
```

The image itself is never written to disk by PersonalAI — only the
instruction text and the model's reply are saved to the conversation
(under a "vision" session by default, or `--session` for your own name).
Pull a vision-capable model first: `ollama pull llava` (the default) or
`ollama pull llama3.2-vision` (bigger, better, needs more VRAM).

## Choosing a backend

PersonalAI talks to whichever backend is configured, through the exact
same `ChatService` and CLI/GUI regardless of which one:

| Backend | What it is | API key |
|---|---|---|
| `ollama` (default) | A local Ollama server - fully offline | none |
| `anthropic` | Claude, via Anthropic's API | `ANTHROPIC_API_KEY` |
| `openai` | OpenAI, a Codex-compatible endpoint, or any other API exposing the same `/chat/completions` shape (OpenRouter, a local llama.cpp/vLLM server, LM Studio, ...) | `OPENAI_API_KEY` |

Switch with:
```powershell
myai config set backend anthropic
myai backends              # see which one is active and whether its key is set
```

API keys are **never stored in config** - only read from the
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` environment variables, same
convention as the official SDKs. Set one in your shell profile (or with
`setx ANTHROPIC_API_KEY "..."` on Windows, then open a new terminal) and
it just works; `myai config set anthropic_api_key ...` is deliberately
refused with a pointer to this instead, so a key never ends up sitting
in a JSON file or your shell history.

For `openai`, point `openai_base_url` at whatever endpoint you're
actually using (defaults to OpenAI's own API):
```powershell
myai config set openai_base_url https://my-codex-endpoint.example/v1
```

`models.<task>` keeps working exactly the same after switching - a model
NAME's meaning just depends on which backend is active (e.g.
`models.story` might be `llama3.1` under Ollama or `claude-sonnet-5`
under Anthropic):
```powershell
myai config set models.story claude-sonnet-5
```

Changing backend in the GUI's **File → Settings…** takes effect
immediately, same as changing a URL - no restart needed.

## How it's organized

```
personalai/
  cli.py                 argument parsing + the chat/caption/list/show/config commands
  core/
    config.py             per-machine settings (~/.personalai/config.json)
    conversation.py        one JSON file per saved conversation
    errors.py
  services/
    llm_client.py           the LLMClient contract every backend implements
    ollama_client.py        local Ollama server
    anthropic_client.py     Claude (Messages API)
    openai_client.py        OpenAI / Codex-compatible / any OpenAI-shaped API
    backend_factory.py      builds the active client from Config.backend
    chat_service.py         per-task system prompts + turn orchestration
    context_service.py      --context file/folder loading + truncation
    vision_service.py       image loading/encoding for the caption task
    voice_service.py        mic recording + local transcription (faster-
                            whisper) + text-to-speech (pyttsx3), used by
                            the Voice tab; all lazily-imported/optional
  gui_main.py             bare GUI entry point (no argparse) - used by
                          the frozen .exe and Run-PersonalAI-GUI.bat
  ui/                     desktop GUI (`myai gui`) - a thin layer over
                          the same services, nothing here is required
                          for the CLI, and PySide6 is only imported when
                          this subcommand actually runs
```

Everything under `services/` and `core/` is plain Python with no CLI,
GUI, or network mocking baked in, so it's exercised directly by the test
suite (`conda run -n personalai python -m pytest tests -q`) without
needing a real Ollama server running.

## Roadmap

- ✅ **CLI core** — chat/story/code modes, saved conversations, file
  context, per-task model config.
- ✅ **Desktop GUI** (`myai gui`) — a window over the same
  `ChatService`/`ConversationStore`: a Chat tab (session list, task
  picker, streaming transcript, file/folder context attach), a Voice
  tab (talk to it out loud), and a Caption Image tab (pick an image,
  ask about it, streamed description).
- ✅ **Vision/captioning mode** — `myai caption`, using an Ollama vision
  model (`llava` by default), independent of any specific project's
  tagging pipeline.
- ✅ **Folder context** — `--context` accepts a file or a whole folder
  (recursively combines its text files), in both the CLI and the GUI's
  "Attach folder…" button.
- ✅ **Swappable backends** — Ollama (default, offline), Claude
  (Anthropic), or any OpenAI-compatible API (OpenAI, Codex-style
  endpoints, OpenRouter, a local server) - one `myai config set backend
  <name>` away, no code changes. See
  [Choosing a backend](#choosing-a-backend).
- ✅ **A dependable desktop app** — multi-line Enter-to-send input, a
  colored transcript, right-click session delete, a system tray icon
  (closing the window minimizes instead of quitting), remembered window
  size/position, and model pick-lists in Settings populated from what's
  actually pulled in Ollama.
- ✅ **A Voice tab you actually talk to** — tap a pulsing animated orb
  once to start talking; it detects when you've gone quiet and stops on
  its own (no second tap needed), transcribes locally (faster-whisper,
  CPU-only, with silence/noise filtering so it doesn't hallucinate text
  out of dead air), sends it to the same assistant, and speaks the
  reply back (local TTS via Windows SAPI5/pyttsx3) - all fully offline.
  The Chat tab stays typing-only on purpose. See
  [Voice input and reading replies aloud](SETUP.md#voice-input-and-reading-replies-aloud).
- ✅ **A real standalone .exe** — `Build-PersonalAI-Exe.ps1` packages the
  GUI as `PersonalAI.exe`, no conda/terminal needed to launch it. See
  [Building a standalone .exe](SETUP.md#building-a-standalone-exe).
- Possible next: a global hotkey for summoning PersonalAI from anywhere
  without clicking the tray icon first.

## A note on model choice

PersonalAI doesn't ship or recommend any specific model beyond the
defaults (`llama3.1` for general/story, `qwen2.5-coder` for code, both
via Ollama) — pick whatever fits your hardware and taste, and set it
with `myai config set models.<task> <model-name>`. What "fits" means
depends on the backend: for Ollama, larger/better local models need
more VRAM (or run slower on CPU - a small model like `llama3.2:3b` is a
solid, genuinely usable choice on a CPU-only laptop); for Claude/OpenAI,
it just means picking whichever hosted model name you want to pay for.
