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
- [Voice input and reading replies aloud](#voice-input-and-reading-replies-aloud)
- [Building a standalone .exe](#building-a-standalone-exe)
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

This is meant to be a genuinely usable everyday interface, not just a
thin wrapper you fall back to when you forget a command — the terminal
stays around for one-shot messages and scripting/automation, but for
regular back-and-forth conversation the window is the intended way to
use PersonalAI. If you'd rather not type commands, launch it:

```powershell
myai gui
```

Or double-click **`Run-PersonalAI-GUI.bat`**, or build a real standalone
`.exe` (see [Building a standalone .exe](#building-a-standalone-exe)
below) if you couldn't find an executable to click.

It has three tabs, all talking to the exact same settings and saved
conversations as the CLI (a session started with `myai story` shows up
in the GUI's session list, and vice versa):

- **Chat** — typing only, on purpose. A task dropdown (general/story/
  code), a list of saved sessions on the left (right-click one to
  delete it), a colored streaming transcript, and "Attach file…" /
  "Attach folder…" buttons (same idea as `--context` on the command
  line — pick a file or a whole folder and its content gets prepended
  to your next message; attaching multiple times combines them). The
  input box is multi-line: **Enter sends, Shift+Enter adds a new
  line** — handy for longer story or code messages.
- **Voice** — an actual talk-to-it assistant. Tap the pulsing orb once
  and say something - it notices when you've gone quiet and stops on
  its own, then answers back both as text and out loud. See
  [Voice input and reading replies aloud](#voice-input-and-reading-replies-aloud)
  below.
- **Caption Image** — choose an image, optionally type what you want to
  know about it, click "Caption it".

A few things make it feel like a normal desktop app instead of a script
with a window glued on: it remembers its size/position between
launches, minimizing sends it to the system tray, closing it (the X
button) exits, and right-clicking the tray icon can bring the window
back — and **File → Settings…** edits the same things
as `myai config set` (backend, Ollama URL, per-task models — picked
from a dropdown of whatever's actually pulled in Ollama instead of
typed free-hand — context size limit, and the voice input model size).

### Memory, models, and backups

Use **Chat → Review memory** when a conversation contains preferences or
lasting context worth carrying forward. Nexus proposes short facts, but none
are remembered unless you check and save them in the review dialog. You can
still edit approved memory directly in **Settings → Assistant**.

**Settings → Models** lists installed Ollama models and lets you pull a model
or remove a selected local model. **Settings → Assistant → Export backup**
creates a ZIP containing `config.json` (including approved memory) and every
conversation. The same backup is available from the command line with
`myai export nexus-backup.zip`.

On Windows, **Settings → Assistant** can enable `Ctrl+Alt+N` to open Nexus
from anywhere. It is off by default and does nothing if another app already
owns that shortcut.

The first time you run `myai gui`, if you see an error mentioning
PySide6, the GUI's one extra dependency didn't get installed — re-run
`Install-PersonalAI-Env.ps1 -Dev` (it's in `requirements.txt` and should
have installed automatically; this is only a fallback for older
installs).

## Voice input and reading replies aloud

This lives in its own **Voice** tab, separate from Chat - a pulsing
animated orb you tap once to start talking, rather than a mic button
bolted onto a text box. Both directions are fully local/offline - no
audio is ever sent anywhere over the network. If a package below isn't
installed, the orb (or the "Speak replies aloud" checkbox) just shows
up disabled with a tooltip explaining why, instead of crashing
anything.

**One turn of a conversation:**
1. Tap the orb — it turns red and starts recording from your default
   microphone ("Listening…").
2. Just say what you want. **You don't need to tap anything to stop** -
   it notices when you've gone quiet for about a second and ends the
   recording on its own (you can still tap the orb early if you want to
   cut it off sooner).
3. It transcribes locally (via `faster-whisper`, CPU-only), sends your
   words to the assistant the same as typing them would, streams the
   reply into the log below the orb ("Thinking…"), then speaks it back
   out loud ("Speaking…") before returning to idle, ready for the next
   turn.

If it doesn't hear anything clearly above the room's background noise,
it says so ("Didn't hear anything - tap to try again") and goes back to
idle instead of guessing - Whisper-family models are known to
hallucinate filler text like "you" or "Thank you." when fed silence, so
this checks for actual speech itself rather than trusting the model to
know the difference. Nothing auto-sends anything you didn't actually
say out loud, and the whole exchange - what you said and what it
replied - stays visible as text in the log too, in case the
transcription or the speech synthesis is hard to follow.

If it consistently mishears you, cuts you off too early/late, or
mistakes silence for speech, your mic's input level might just need
adjusting in Windows' own Sound settings (too quiet makes real speech
look like background noise; too hot makes background noise look like
speech) - there's no in-app sensitivity setting for this yet.

The first recording after installing/switching model size downloads a
small model from Hugging Face (~75-150MB depending on size, cached
afterward under `~/.cache/huggingface` — fully offline from then on).
Pick the size in **File → Settings… → Voice input model**:
`tiny.en` (fastest, least accurate) / `base.en` (default, good balance)
/ `small.en` (slower, more accurate) — all English-only and CPU-friendly.

**Reading replies aloud** is on by default in the Voice tab (that's the
point of it) — uncheck "Speak replies aloud" there if you'd rather use
it as voice-to-text dictation without the spoken reply. Uses `pyttsx3`,
which drives Windows' own built-in text-to-speech (SAPI5) — no model
download, no internet, whatever voice is set in Windows' own Speech
settings.

If these packages didn't install automatically (older install, or a
sandboxed/restricted environment where `sounddevice`'s microphone access
or `pyttsx3`'s SAPI5 hookup couldn't build), re-run
`Install-PersonalAI-Env.ps1 -Dev` or install them by hand:
```powershell
conda run -n personalai pip install sounddevice faster-whisper pyttsx3
```

## Building a standalone .exe

`myai gui` (or `Run-PersonalAI-GUI.bat`) both launch the desktop app
through the conda environment - completely fine day to day, but if you'd
rather have a real `PersonalAI.exe` you can pin to your taskbar or hand
to someone else without them installing Anaconda, build one:

```powershell
powershell -ExecutionPolicy Bypass -File Build-PersonalAI-Exe.ps1
```

This produces `dist\PersonalAI\PersonalAI.exe` — double-click it, no
conda or terminal involved at all. Add `-Shortcut` to also drop a
"PersonalAI" shortcut on your Desktop:

```powershell
powershell -ExecutionPolicy Bypass -File Build-PersonalAI-Exe.ps1 -Shortcut
```

The build takes a few minutes (`faster-whisper`'s speech-recognition
backend is the biggest piece) and `dist\`/`build\` are gitignored -
they're disposable, rebuild any time rather than committing them. If
Windows SmartScreen or your antivirus flags the freshly-built .exe the
first time you run it, that's a common false positive for unsigned
PyInstaller executables, not a sign anything is wrong — choose "More
info → Run anyway" (SmartScreen) or add an exception (antivirus).

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

**The Voice tab's orb / "Speak replies aloud" checkbox is greyed out**
The optional package behind it isn't installed - hover the control for a
tooltip naming which one (`sounddevice` + `faster-whisper` for the orb,
`pyttsx3` for speaking replies). Install it with `conda run -n
personalai pip install <name>` and restart the GUI.

**Recording works but nothing gets transcribed, or it's very slow**
The first transcription with a given voice model size downloads it from
Hugging Face - if you're offline at that moment it'll fail. Try a
smaller model size (`tiny.en`) in Settings if it's consistently slow;
like text models, this runs on CPU and a bigger size is a real
speed/accuracy trade-off, not a bug.

**It keeps transcribing to "you" (or "Thank you."), or the Voice tab
always says "Didn't hear anything" even when I'm talking**
Run the built-in diagnostic to find out whether the mic itself is the
problem, independent of the Voice tab:
```powershell
myai mic-test
```
It lists your input devices, records a few seconds while you talk, and
prints the actual levels it saw plus a verdict. A peak level near 0
means the mic isn't being picked up at all - check Windows Sound
settings → Input: is the right device selected as default, is it
muted, is the volume/gain turned up, is it actually plugged in/paired?
If `mic-test` shows healthy levels but the Voice tab still says
"Didn't hear anything", it now also prints the peak level right in its
own status message ("Didn't hear anything (peak input level: N)") -
that's useful detail to include if you need to report it, since it
means the app's own sensitivity needs adjusting rather than the mic.

**On some newer laptops, `mic-test` shows several devices with the same
mic's name** (e.g. multiple "Microphone Array" entries) - only one of
them may actually carry sound. This is a Realtek/Intel "Smart Sound
Technology" thing: the OS-picked default is often a legacy endpoint
that's silently disconnected from the real hardware, while the one that
works is usually named with "**with SST**" in it. Use `myai mic-test
--device N` to try each one from the list until you find one with real
levels, then `myai config set mic_device N` (or Settings' Microphone
dropdown) to make the Voice tab use it. These "with SST" endpoints can
also be flaky about being *reopened* - if one that worked suddenly
stops responding to `mic-test` too (not just the Voice tab), that's a
driver-level lockup, not this app losing track of anything; restarting
the "Windows Audio" service (services.msc) or rebooting typically
clears it.

**The built .exe won't launch, or the mic/read-aloud controls work in
`myai gui` but not in the frozen .exe**
PyInstaller has to explicitly collect a few native pieces
(`sounddevice`'s bundled PortAudio DLL, `faster-whisper`'s ctranslate2
backend) that its static analysis can't see on its own -
`personalai.spec` already does this, but if a rebuilt .exe still
misbehaves, `myai gui` through the conda env is the reliable fallback
while you sort out the frozen build.

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
