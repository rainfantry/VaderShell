# Changelog

All notable changes to VaderShell. Built ground-up in a single session — this log
tells the story of how it came together, and why each piece exists.

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
