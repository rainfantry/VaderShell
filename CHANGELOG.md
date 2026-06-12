# Changelog

All notable changes to VaderShell. Built ground-up in a single session — this log
tells the story of how it came together, and why each piece exists.

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
