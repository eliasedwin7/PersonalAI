# Setup Guide

Step-by-step: installing Ollama (the default, fully-offline backend),
installing PersonalAI, and having your first conversation. Everything
below was actually run start-to-finish on a plain CPU-only laptop (no
discrete GPU, 16GB RAM) - it's a genuinely light setup, not just a
theoretical one.

**Contents**
- [Before you start](#before-you-start)
- [Step 1 - Install Ollama](#step-1---install-ollama)
- [Step 2 - Install PersonalAI](#step-2---install-personalai)
- [Step 3 - Your first conversation](#step-3---your-first-conversation)
- [Everyday use](#everyday-use)
- [The desktop app](#the-desktop-app)
- [Captioning images](#captioning-images)
- [Choosing models](#choosing-models)
- [Using Claude, OpenAI, or a Codex-compatible API instead](#using-claude-openai-or-a-codex-compatible-api-instead)
- [Troubleshooting](#troubleshooting)
- [Uninstalling / starting over](#uninstalling--starting-over)

---

## Before you start

You need:

- **Windows 10/11**
- **Anaconda** or **Miniconda** ([anaconda.com/download](https://www.anaconda.com/download))
  for PersonalAI's own tiny Python environment.
- A decent amount of free RAM/VRAM to run a model - or none at all if
  you'd rather use Claude/OpenAI instead of a local model (see
  [Using Claude, OpenAI, or a Codex-compatible API instead](#using-claude-openai-or-a-codex-compatible-api-instead)).
  For a local model: a small one (2-3B parameters, e.g. `llama3.2:3b`)
  runs comfortably on CPU alone in a few GB of RAM and a few seconds per
  reply - genuinely fine for a laptop with no GPU. A 7-8B model still
  works on CPU, just slower; anything bigger really wants a GPU with
  8GB+ VRAM.

PersonalAI itself has no GPU requirement and installs in seconds — the
model is what needs the hardware, and that's Ollama's job, not
PersonalAI's.

## Step 1 - Install Ollama

1. Download and install Ollama from **[ollama.com](https://ollama.com)**
   — it's a normal Windows installer, no account or sign-in needed.
2. Open a terminal (any terminal — Ollama isn't tied to Anaconda) and
   pull a model. On a laptop with no discrete GPU, start small - it's
   genuinely usable, not a toy:
   ```powershell
   ollama pull llama3.2:3b
   ```
   ~2GB download, replies in a handful of seconds on CPU alone (Step 3
   below points PersonalAI at it). If you have a real GPU (8GB+ VRAM) or
   don't mind slower replies, the bigger `llama3.1` (PersonalAI's
   out-of-the-box default) gives noticeably better quality:
   ```powershell
   ollama pull llama3.1
   ```
3. (Optional, for coding help) Pull a coding-focused model too:
   ```powershell
   ollama pull qwen2.5-coder
   ```
4. Ollama runs as a background service after install — you don't need to
   manually start anything before using PersonalAI. You can check it's
   alive any time with:
   ```powershell
   ollama list
   ```

## Step 2 - Install PersonalAI

1. Open **Anaconda Prompt** and navigate to the `PersonalAI` folder:
   ```powershell
   cd "C:\path\to\PersonalAI"
   ```
2. Run the installer:
   ```powershell
   powershell -ExecutionPolicy Bypass -File Install-PersonalAI-Env.ps1 -Dev
   ```
   This creates a small, isolated `personalai` conda environment (kept
   completely separate from any other Python setup on your machine),
   installs PersonalAI into it, and checks whether Ollama is reachable
   (a nice-to-have check, not required to finish installing). Safe to
   re-run any time.

## Step 3 - Your first conversation

If you pulled the small `llama3.2:3b` model in Step 1, point PersonalAI
at it (otherwise skip this - `llama3.1` is already the default):
```powershell
conda run -n personalai myai config set models.general llama3.2:3b
conda run -n personalai myai config set models.story llama3.2:3b
```

```powershell
conda run -n personalai myai chat "what can you help me with?"
```

You should see a streamed reply. That's it — a `~/.personalai/` folder
was just created to hold your settings and conversation history.

Try the other modes:

```powershell
conda run -n personalai myai story
```
(no message → drops you into an interactive back-and-forth; type `exit`
or press Ctrl+D to leave)

```powershell
conda run -n personalai myai code "write a Python function that reverses a linked list"
```

Or double-click **`Run-PersonalAI.bat`** for a quick interactive general
chat without typing any commands.

## Everyday use

- **Conversations are remembered automatically.** `myai story` always
  continues the same "story" thread unless you give it `--session
  some-name` to start (or return to) a named one. `myai list` shows every
  saved thread; `myai show NAME` prints the whole transcript.
- **`--reset`** wipes a session's history and starts fresh:
  ```powershell
  myai story --reset "let's start a new outline"
  ```
- **`--context FILE`** feeds a local file's content to the model as
  reference material alongside your message — this is how you point
  PersonalAI at something specific, like a story outline or a piece of
  code, without it needing to live inside any particular project:
  ```powershell
  myai story --context "C:\MyNovel\outline.md" "continue chapter 5"
  ```
  Large files are automatically truncated (keeping the *end*, since
  that's usually the most relevant part for "continue from here") so you
  don't accidentally overflow the model's context window.
- **`--context` also accepts a whole folder** — every text file inside
  it (recursively; `.md .txt .rpy .py .json .yaml .csv` and a few more)
  gets combined, each under its own filename header, and the *combined*
  text is truncated the same way a single file is:
  ```powershell
  myai story --context "C:\MyNovel\chapters" "continue where chapter 5 left off"
  ```
  Capped at 50 files as a safety limit — point it at a chapters folder,
  not your whole project.
- **Everything is a plain JSON file** under `%USERPROFILE%\.personalai\`
  — `config.json` for settings, `conversations\<name>.json` per thread.
  Back them up, inspect them, or delete one you don't want with a normal
  file manager; there's no database involved.

## The desktop app

If you'd rather not type commands, launch the window instead:

```powershell
myai gui
```

It has two tabs, both talking to the exact same settings and saved
conversations as the CLI (a session started with `myai story` shows up
in the GUI's session list, and vice versa):

- **Chat** — a task dropdown (general/story/code), a list of saved
  sessions on the left, a streaming transcript, and "Attach file…" /
  "Attach folder…" buttons (same idea as `--context` on the command
  line — pick a file or a whole folder and its content gets prepended
  to your next message; attaching multiple times combines them).
- **Caption Image** — choose an image, optionally type what you want to
  know about it, click "Caption it".

**File → Settings…** in the window edits the same things as `myai config
set` (Ollama URL, per-task models, context size limit).

The first time you run `myai gui`, if you see an error mentioning
PySide6, the GUI's one extra dependency didn't get installed — re-run
`Install-PersonalAI-Env.ps1 -Dev` (it's in `requirements.txt` and should
have installed automatically; this is only a fallback for older
installs).

## Captioning images

Point PersonalAI at any image and ask about it:

```powershell
ollama pull llava
myai caption "C:\path\to\photo.png"
myai caption "C:\path\to\photo.png" "is this indoors or outdoors?"
```

With no instruction, it just describes the image. Like the other modes,
the conversation (your questions + the model's answers, as text) is
saved under a "vision" session by default — the image file itself is
never copied or written to disk by PersonalAI, only sent to Ollama for
that one request.

`llava` is the default vision model and works well for general use. If
you have the VRAM for it, `llama3.2-vision` tends to give more detailed,
accurate descriptions:

```powershell
ollama pull llama3.2-vision
myai config set models.vision llama3.2-vision
```

## Choosing models

Different tasks default to different models:

```powershell
myai config show
```
```
models:
  general  = llama3.1
  story    = llama3.1
  code     = qwen2.5-coder
  vision   = llava
```

Change any of them (after pulling the model with `ollama pull <name>`):

```powershell
myai config set models.code deepseek-coder-v2
myai config set models.story mixtral
```

If a model is too slow, try a smaller one in the same family (e.g. an
`:8b` or `:7b` tag instead of a larger one) — `ollama pull <model>:<tag>`
and then point PersonalAI at the exact tag.

If your Ollama server lives on a different PC (say, a machine with a
better GPU), point PersonalAI at it over your network instead of
`127.0.0.1`:

```powershell
myai config set ollama_url http://192.168.1.50:11434
```

## Using Claude, OpenAI, or a Codex-compatible API instead

Everything above uses Ollama (local, offline, default). If you'd rather
use a hosted model - Claude, OpenAI, or anything exposing an
OpenAI-compatible `/chat/completions` API (Codex-style endpoints,
OpenRouter, a teammate's shared server) - swap the backend instead of
installing anything:

**Claude (Anthropic):**
```powershell
setx ANTHROPIC_API_KEY "sk-ant-..."
```
Close and reopen your terminal (so the new environment variable is
picked up), then:
```powershell
myai config set backend anthropic
myai config set models.story claude-sonnet-5
myai chat "hello"
```

**OpenAI (or a Codex-compatible / other OpenAI-shaped endpoint):**
```powershell
setx OPENAI_API_KEY "sk-..."
```
Reopen your terminal, then:
```powershell
myai config set backend openai
myai config set models.story gpt-4o
# only if you're NOT using OpenAI's own API - point at your endpoint:
myai config set openai_base_url https://my-codex-endpoint.example/v1
myai chat "hello"
```

Check which backend is active and whether its key is set at any time
with `myai backends`. **API keys are never written to
`~/.personalai/config.json`** — only read from the environment variables
above, so `myai config set anthropic_api_key ...` / `openai_api_key ...`
are deliberately refused rather than silently doing something unsafe.

Switching back to Ollama is the same command:
```powershell
myai config set backend ollama
```

In the desktop app, all of this is under **File → Settings…** (backend
dropdown + base URL field) except the keys themselves, which still only
come from the environment variables — the Settings dialog has no field
for typing one in.

## Troubleshooting

**"Cannot reach Ollama at http://127.0.0.1:11434"**
Ollama isn't running (or isn't installed yet). Run `ollama list` in any
terminal to check; if that also fails, reinstall from
[ollama.com](https://ollama.com).

**"Ollama rejected the request... is model 'X' pulled?"**
You asked for a model that isn't downloaded yet. Run `ollama pull <name>`
first, or check the exact name/tag with `ollama list`.

**Replies are very slow**
That's expected if the model is running on CPU rather than GPU, or if
it's larger than your hardware comfortably fits. Try a smaller model
(see [Choosing models](#choosing-models)) — Ollama will tell you if a
model doesn't fit your available memory when you try to pull/run it.

**"ERROR: conda not found in PATH"**
You ran the installer from a regular Command Prompt/PowerShell window
instead of **Anaconda Prompt**. Reopen "Anaconda Prompt" from the Start
menu and try again.

**`myai gui` complains it can't find PySide6**
Re-run `Install-PersonalAI-Env.ps1 -Dev` — PySide6 is in
`requirements.txt` and should install with everything else; this only
happens on an older install from before the GUI existed.

**Image descriptions are vague, wrong, or `myai caption` errors that the model doesn't support images**
Make sure the model set for `models.vision` is actually a vision-capable
one (`llava`, `llama3.2-vision`, `bakllava`, etc.) — a text-only model
like `llama3.1` will either ignore the image or Ollama will reject the
request. Check with `myai config show`.

**"No Anthropic API key found" / "No API key found" (OPENAI_API_KEY)**
The `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` environment variable isn't
set (or isn't visible to this terminal yet). After running `setx`, close
and reopen the terminal — `setx` only affects *new* processes, not the
one you ran it from. Confirm with `myai backends`, which shows whether
each key is currently set.

**Switched backend but `myai chat` still seems to hit the old one**
In the CLI this can't happen (each command rebuilds its client from
current config) - double check with `myai config show` that `backend`
actually changed. In the GUI, switching backend in Settings rebuilds the
live connection immediately on clicking OK; if something still looks
off, restart `myai gui`.

**I want to point this at a Dune-Remaster (or any other project) file or folder**
You don't need PersonalAI to live inside that project — just pass the
full path with `--context` (a file or a whole folder both work):
```powershell
myai story --context "C:\Users\you\My Drive\Game\Dune-Remaster\DuneRemaster\STORY_OUTLINE.md" "continue chapter 3"
```

## Uninstalling / starting over

- **Remove just the environment** (keeps your conversations/settings):
  ```powershell
  conda env remove -n personalai
  ```
- **Remove your conversations and settings**: delete the folder
  `%USERPROFILE%\.personalai\`.
- **Remove Ollama and downloaded models**: uninstall it like any other
  Windows program (Settings → Apps); this frees the disk space used by
  pulled models, which can be several GB each.
