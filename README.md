# VaderShell

A lean, branded wrapper that turns the **Claude CLI** into a personal **terminal agent** and a **Discord bot** — with one-line switching to Kimi or OpenRouter.

The Claude path drives the *real* `claude` binary, so it inherits your logged-in Claude Code session: full agent tools, your `CLAUDE.md`, your skills, your subscription. No API token, no spoofing, no rate-limit games.

![VaderShell in the terminal](docs/terminal.png)

![VaderShell answering in Discord](docs/discord.png)

## Why it works

Most "use my Claude subscription in my own app" attempts hand-roll an API call with an OAuth token — which Anthropic rate-limits hard (instant 429s, even when your plan is barely used). VaderShell sidesteps that entirely: it **shells out to the real `claude` CLI** you're already logged into, inheriting the exact auth that works in your terminal — full tools, your memory and skills, your subscription's allowance — with nothing to fake.

## Install

1. Clone this repo.
2. Python 3.11+:
   ```
   python -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
3. Install **Claude Code** and log in (`claude`, then `/login` → your subscription). The default `claude` provider drives this CLI.
4. `copy .env.example .env` and fill in what you need (the `claude` path needs nothing).

## Run

Terminal agent:
```
.\22div.ps1
```
Discord gateway (stays running, listens to your server):
```
.\gateway.ps1
```
Tip: add `function vader { & 'C:\path\to\VaderShell\22div.ps1' }` to your PowerShell profile for a one-word launch.

## Switch brains

Edit `.env` → `VADER_PROVIDER`:

| Value | Brain |
|---|---|
| `claude` | Claude via the real CLI (uses your login — recommended) |
| `kimi` | Kimi (set `KIMI_API_KEY`) |
| `openrouter` | any model via OpenRouter (set `OPENROUTER_API_KEY` + `VADER_MODEL`) |

## Discord bot setup

1. **https://discord.com/developers/applications** → **New Application** → name it.
2. **Bot** tab → **Reset Token** → copy it into `.env` as `DISCORD_BOT_TOKEN`.
3. Same tab → **Privileged Gateway Intents** → enable **MESSAGE CONTENT INTENT** (required to read messages).
4. **OAuth2 → URL Generator** → scope **`bot`**; bot permissions **View Channels, Send Messages, Read Message History**. Open the generated URL and add the bot to your server.
5. *(Optional, recommended)* Lock the bot to yourself: set `VADER_DISCORD_UID` to your Discord user ID (Developer Mode → right-click your name → Copy User ID).
6. Run `.\gateway.ps1` and message the bot in your server — it answers with full Claude + tools.

## A note on the `claude-api` provider

There's also a `claude-api` provider that calls the Anthropic API directly with an OAuth/API token. It works, but gets rate-limited aggressively even on an idle subscription. Prefer the default `claude` (CLI) path.

## Layout

| Path | Role |
|---|---|
| `vader/banner.py` | startup logo |
| `vader/auth.py` | provider + credential resolution |
| `vader/core.py` | conversation + streaming engine (drives `claude`) |
| `vader/terminal.py` | terminal REPL |
| `vader/gateway_discord.py` | Discord bot |
| `22div.ps1` / `gateway.ps1` | launchers |
| `healthcheck.py` | smoke test |

---

Built by [rainfantry](https://github.com/rainfantry).
