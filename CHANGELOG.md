# Changelog

All notable changes to VaderShell. Built ground-up in a single session — this log
tells the story of how it came together, and why each piece exists.

## 0.5.0 — persistent memory + self-taught skills

VADER can now LEARN and keep it. Memory and skills live on disk under `~/.vader`
(override `VADER_HOME`), outside the repo, so they survive restarts — and because
the system prompt reads them fresh every turn, anything saved is in effect on the
very next message too.

### Memory (`vader/tools.py`)
- `remember(fact)` — append a durable fact/preference to long-term memory.
- `recall()` — read it back. Memory is auto-folded into the system prompt each turn.

### Skills (`vader/tools.py`)
- `save_skill(name, description, steps)` — VADER writes its own reusable workflow as
  a markdown skill that persists. The skills index is shown in the prompt.
- `use_skill(name)` — load a skill's full steps before doing a matching task.
- `list_skills()` — see what it has learned.

### Prompt wiring (`vader/core.py`)
- `_system_prompt()` folds the live memory text and skills index in every turn (read
  from disk), so saved learning applies immediately and after a `/restart`.
- Dev guidance now tells VADER to `remember()` lasting facts and `save_skill()` reusable
  workflows, and to `use_skill()` before repeating a known task.
- Verified end-to-end on Kimi K2.5: it saved a skill, a fresh agent loaded it from
  disk, and it then executed the skill's steps autonomously.

## 0.4.0 — dev workspace + eyes (screenshots the model can see)

Turns the Kimi tool belt into a proper software-dev agent: a real workspace, and
the ability to *see* its own work via screenshots fed back to the (vision-capable)
model — the build → screenshot → look → fix loop a human dev uses.

### Workspace (`vader/tools.py`)
- New `VADER_WORKSPACE` (default `~/vader-workspace`, auto-created). `run_terminal`
  runs there and relative file paths resolve there, so VADER clones/creates/builds
  repos in one place instead of junking up home.
- Bumped limits for real dev work: tool output cap 6k → 12k chars, command timeout
  120s → 300s, and (in `core.py`) tool-step cap 16 → 40 per turn.

### Eyes — screenshots (`vader/tools.py` + `vader/core.py`)
- `screenshot_desktop` — capture the whole screen to PNG (Windows .NET via
  PowerShell; no dependency).
- `screenshot_url` — render a web page headless via Edge/Chrome to PNG (no
  dependency, no Playwright). Pair with a dev server: build → `screenshot_url
  http://localhost:PORT` → look → fix.
- The agent loop now feeds captured screenshots back to the model as inline images
  (base64), so a vision model actually *sees* them and reasons over what's on
  screen. Toggle with `VADER_VISION` (default on). Verified end-to-end on Kimi K2.5.

### Dev guidance (`vader/core.py`)
- The system prompt now steers VADER as a dev agent: work in the workspace, use the
  inherited gh/git auth to clone/create (`gh repo create --private`)/commit/push,
  verify by running/building/testing and screenshotting UIs, branch before risky
  work, never force-push, and never add AI/Claude attribution to commits.

## 0.3.0 — tools for the Kimi/OpenRouter brain

Until now only the **claude** brain could act (it shells out to the real `claude`
CLI, which has full tools). The kimi/openrouter path was a plain chat — a mouth with
no hands. That defeats the point of a gateway. This release gives those brains a real
tool belt, so VADER can actually *do* things on any brain.

### Tool belt (`vader/tools.py`)
- **`run_terminal`** — run shell commands (PowerShell / cmd / bash) and get exit code,
  stdout and stderr. This is the workhorse: `gh` CLI, `git` clone/commit/push (private
  repos via the machine's logged-in auth), `npm`/`dotnet`/`python` build & run, installs
  — all of it is just a command. Runs in the home directory, inheriting the real env.
- **`web_search`** — DuckDuckGo search (no API key) → titles, URLs, snippets.
- **`fetch_url`** — fetch a page and return its readable text (tags stripped).
- **`read_file` / `write_file` / `list_dir`** — file I/O, paths resolving from home.
- Output is capped per call so a chatty command can't blow the model's context.

### Agent loop (`vader/core.py`)
- The OpenAI-compatible path (Kimi/OpenRouter) is now a **tool-using agent**: ask the
  model → if it calls tools, run them and feed the results back → repeat until it
  answers with no more calls (bounded at 16 rounds). It streams `tool` / `tool_result`
  / `text` events, so you watch it act live in both the terminal and Discord — exactly
  like the claude path.
- The brain is told what it can reach (tools, the machine, the inherited auth) via an
  added system block, and steered to verify its work by actually running it.

### Deps
- Added `ddgs` (maintained DuckDuckGo search client) for `web_search`.

## 0.2.0 — native slash commands

### Slash commands (the `/` picker)
- VADER now registers **native Discord slash commands**, shown under its own name in
  the picker — so they don't collide with another bot's commands in a shared server.
  `/help`, `/plan <task>`, `/model <name>`, `/reset`, `/restart`.
- `/help` lists every command and what it does, so you never have to remember them.
- The old typed-text commands still work as a fallback (e.g. before the slash
  commands finish syncing on first launch).
- Commands sync **per-guild** on startup (instant), not globally (slow to propagate).
- Requires the bot to be invited with the `applications.commands` scope (see README).

### Runtime brain switch — `/model`
- `/model opus|sonnet|haiku|kimi` writes a runtime override (`runtime_override.env`,
  gitignored) and reboots onto the new brain — switch models from your phone if one
  model's quota runs dry mid-task, without touching the machine. The override is
  loaded over base config at startup and wins over the launcher's default.

### Setup & docs
- `setup.ps1` — one-step install: creates the venv, installs deps, copies
  `.env.example` → `.env`, and checks for Python and the `claude` CLI.
- `.env.example` now documents **every** variable the code reads, grouped by purpose
  (brain selection, keys, Discord, coalition, advanced overrides).

## 0.1.0 — first release

### The core idea
- VaderShell wraps the **real `claude` CLI** instead of calling the API with a
  borrowed subscription token. Token-spoofing the API gets rate-limited hard
  (instant 429s, even on an idle plan); driving the genuine CLI inherits the auth
  that already works — full tools, your `CLAUDE.md`, your skills, your subscription's
  real allowance. This single decision is why it works where the API approach didn't.

### Architecture
- One `core.Agent` brain; thin front doors (terminal, Discord) both call it.
- `auth.py` resolves the provider (claude / kimi / openrouter / claude-api) from `.env`.
- Replies stream as `(kind, text)` pairs — `thinking` / `tool` / `tool_result` /
  `text` — so any front door can show the work live.

### Terminal agent
- `vader` opens a branded REPL: banner, type-and-stream chat, `/reset`, `/exit`.

### Provider switch
- One line in `.env` (`VADER_PROVIDER`) swaps the brain: Claude (CLI),
  Kimi, or any OpenRouter model. API-key-in-env, no code change.

### Discord gateway
- `vader-gateway` exposes the same brain as a Discord bot — delegate from your phone.
- Locked to the operator's user ID; ignores other bots by default; splits long
  replies under Discord's 2000-char limit.
- In-chat commands: `/plan`, `/reset`, `/restart`. The launcher **supervises** the
  process — `/restart` reboots it (reconnects in seconds) and crashes auto-recover,
  so you can reboot it from your phone even away from the machine.

### Planning council — `/plan`
- A **bounded** two-model deliberation: Claude plans, Kimi plans (independent second
  opinion via OpenRouter), Claude compares both (agree / differ / recommend).
- Each model speaks once, Claude compares once, then it stops and waits for you —
  no model-to-model loop, no runaway cost.
- Runs with full tools + your skills, so Claude can **web-search to verify** a plan,
  not just reason about it.

### Coalition mode
- Point VADER at a server where a *second* bot also answers you; VADER reads that
  bot's reply and posts a second opinion. One-directional (the peer is blind to
  VADER) so it can't loop. Waits for the peer to finish streaming, skips its
  placeholder / status messages, and a cooldown backs it up.

### Models & quota
- Terminal runs on **Opus**; the gateway launcher sets **Sonnet** — lighter for
  phone use and, on most plans, a separate quota that spares the Opus budget.

### Logging
- The gateway logs every event to `gateway.log` (and the terminal), headed by a
  branded banner, so any run can be reviewed after the fact.
