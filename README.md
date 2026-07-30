# PersonalAI

**Your own AI assistant, running entirely on your own PC — no internet, no
account, no API key.**

A tool that talks to [Ollama](https://ollama.com) (a free program that
runs AI chat models locally) and gives you four ready-to-use modes, from
the command line or a small desktop app:

- **`myai chat`** — general-purpose assistant
- **`myai story`** — creative writing / dialogue / worldbuilding collaborator
- **`myai code`** — coding help
- **`myai caption`** — describe or ask questions about an image, using a
  local vision model

Every conversation is saved to a plain JSON file on your disk, so you can
pick up where you left off, list past sessions, or hand a transcript to
someone else. Nothing ever leaves your machine.

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
covers a lot of ground with very little code to trust. The desktop GUI
(`myai gui`) is a thin window on top of the exact same
`ChatService`/`ConversationStore` the CLI uses — a session started with
`myai story` shows up in the GUI's session list too, and vice versa.

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

myai config show                   view current settings
myai config set KEY VALUE          e.g. models.story llama3.1
                                    e.g. models.vision llama3.2-vision
                                    e.g. ollama_url http://192.168.1.50:11434

myai gui                           launch the desktop app
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

## How it's organized

```
personalai/
  cli.py                 argument parsing + the chat/caption/list/show/config commands
  core/
    config.py             per-machine settings (~/.personalai/config.json)
    conversation.py        one JSON file per saved conversation
    errors.py
  services/
    ollama_client.py       thin HTTP client for a local Ollama server
    chat_service.py        per-task system prompts + turn orchestration
    context_service.py     --context file/folder loading + truncation
    vision_service.py      image loading/encoding for the caption task
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
  picker, streaming transcript, file/folder context attach) and a
  Caption Image tab (pick an image, ask about it, streamed description).
- ✅ **Vision/captioning mode** — `myai caption`, using an Ollama vision
  model (`llava` by default), independent of any specific project's
  tagging pipeline.
- ✅ **Folder context** — `--context` accepts a file or a whole folder
  (recursively combines its text files), in both the CLI and the GUI's
  "Attach folder…" button.
- Possible next: a global hotkey / system-tray quick-chat for launching
  PersonalAI without opening a terminal first.

## A note on model choice

PersonalAI doesn't ship or recommend any specific model beyond the
defaults (`llama3.1` for general/story, `qwen2.5-coder` for code) — pick
whatever Ollama model fits your GPU and suits your taste, and set it with
`myai config set models.<task> <model-name>`. Larger/better models need
more VRAM; if a model is too slow or won't load, try a smaller or more
quantized version of the same family.
