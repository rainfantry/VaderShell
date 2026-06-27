# VaderShell

A lean, branded wrapper that turns the **Claude CLI** into a personal **terminal agent** and a **Discord bot** — with one-line switching to Kimi or OpenRouter.

The Claude path drives the *real* `claude` binary, so it inherits your logged-in Claude Code session: full agent tools, your `CLAUDE.md`, your skills, your subscription. No API token, no spoofing, no rate-limit games.

![VaderShell in the terminal](docs/terminal.png)

![VaderShell answering in Discord](docs/discord.png)

VADER reading a second bot and firing a second opinion in a shared channel:

![VADER second-opinion on a peer bot](docs/vafder.png)

## Why it works

Most "use my Claude subscription in my own app" attempts hand-roll an API call with an OAuth token — which Anthropic rate-limits hard (instant 429s, even when your plan is barely used). VaderShell sidesteps that entirely: it **shells out to the real `claude` CLI** you're already logged into, inheriting the exact auth that works in your terminal — full tools, your memory and skills, your subscription's allowance — with nothing to fake.

## Install

1. Clone this repo.
2. One-step setup (Windows PowerShell) — creates the venv, installs deps, copies `.env.example` → `.env`:
   ```
   .\setup.ps1
   ```
3. Install **Claude Code** and log in (`claude`, then `/login` → your subscription). The default `claude` provider drives this CLI.
4. Edit `.env` with your values (the `claude` path needs nothing; the Discord gateway needs a bot token).

## Run

Terminal agent:
```
.\22div.ps1
```
Discord gateway (stays running, listens to your server):
```
.\gateway.ps1
```
In Discord, VADER registers **native slash commands** (the `/` picker, shown under its own name):

| Command | What it does |
|---|---|
| `/help` | List the commands and what they do |
| `/plan <task>` | Two-model planning council (Claude + Kimi + a synthesis) |
| `/model <opus\|sonnet\|haiku\|kimi>` | Switch VADER's brain and reboot onto it |
| `/reset` | Clear VADER's conversation memory |
| `/restart` | Reboot the gateway (reconnects in a few seconds) |

`/restart` reboots a **supervised** process, so it reconnects in seconds and crashes auto-recover (up to 5×) — you can reboot the bot from your phone, away from the machine. `/model` writes a runtime override and reboots onto the new brain (handy if a model's quota runs dry mid-task). The same commands also work typed as plain text, as a fallback before the slash commands sync.

Tip: add `function vader { & 'C:\path\to\VaderShell\22div.ps1' }` to your PowerShell profile for a one-word launch.

## Switch brains

Edit `.env` → `VADER_PROVIDER`:

| Value | Brain |
|---|---|
| `claude` | Claude via the real CLI (uses your login — recommended) |
| `kimi` | Kimi (set `KIMI_API_KEY`) |
| `openrouter` | any model via OpenRouter (set `OPENROUTER_API_KEY` + `VADER_MODEL`) |

## Planning council (`/plan`)

Two models are better than one at catching flaws in a *plan*. `/plan <task>` runs a **bounded** deliberation:

1. **Claude** proposes an approach (plan only, no code).
2. **Kimi** plans the same task independently — a second opinion via OpenRouter.
3. **Claude** compares both: where they agree, where they clash, and what to do.

Bounded by design — each model speaks once, Claude compares once, then it stops and waits for you. No model-to-model loop, no runaway cost. You read both sides and decide. (Needs `OPENROUTER_API_KEY` for the Kimi half.)

The council runs with full tools and your skills, so Claude can **web-search to verify** a plan — checking claims, not just reasoning about them.

```
you › /plan a single-file python script that counts lines in a text file
— planning council: two minds, one task —
CLAUDE:     <approach · risks · steps>
KIMI:       <approach · risks · steps>
SYNTHESIS:  <agree / differ / recommendation>
```

## Discord bot setup

1. **https://discord.com/developers/applications** → **New Application** → name it.
2. **Bot** tab → **Reset Token** → copy it into `.env` as `DISCORD_BOT_TOKEN`.
3. Same tab → **Privileged Gateway Intents** → enable **MESSAGE CONTENT INTENT** (required to read messages).
4. **OAuth2 → URL Generator** → scopes **`bot`** *and* **`applications.commands`** (the second is required for native slash commands); bot permissions **View Channels, Send Messages, Read Message History**. Open the generated URL and add the bot to your server. *(If you added the bot before with only `bot`, re-open this URL with both scopes ticked to enable slash commands — no need to kick it first.)*
5. *(Optional, recommended)* Lock the bot to yourself: set `VADER_DISCORD_UID` to your Discord user ID (Developer Mode → right-click your name → Copy User ID).
6. Run `.\gateway.ps1` and message the bot in your server — it answers with full Claude + tools.

## Coalition mode (optional)

Point VADER at a server (or channel) where a *second* bot also answers you, and it reads that bot's replies and posts a second opinion:

- One-directional — VADER reads the peer; the peer never sees VADER — so it **can't loop**.
- VADER waits for the peer to finish streaming (debounce), then reads the **final** message — skipping `Thinking…` placeholders and status/housekeeping spam.
- A cooldown is the backup against runaway.

Set `VADER_COALITION_SERVER_ID` (and optionally `VADER_PEER_BOT_ID`). The peer bot **must ignore bots**, or the one-way guarantee breaks.

## Models & quota

- **Terminal → Opus** (the heavy brain — use it at the machine).
- **Gateway → Opus 4.7** — the launcher sets `VADER_CLAUDE_MODEL=claude-opus-4-7`. Legacy Opus for phone use.
- Override per surface with `VADER_CLAUDE_MODEL`.

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

---

## TODO — Release Blackops

_Automated read-only assessment — what a full public-release pass would do for this repo. Suggestions only; nothing above has been changed or removed._

- [ ] **AI/Claude attribution detected in git history — scrub it** (`filter-branch` + force-push; nuke-and-recreate if a 0-star/0-fork repo and the orphaned SHA lingers).
- [ ] Add discovery topics for SEO (`gh repo edit --add-topic ...`, up to 20).
- [ ] Cut a tagged release (`v1.0.0`); attach a build artifact if this ships a binary/app.
- [ ] Verify a clean from-scratch build/run against the README quick start (produce a real artifact, don't trust the docs).
- [ ] If this is a desktop app, make a self-contained build (bundle runtime assets/models into the binary; confirm it runs with no external files).

<sub>Workflow: https://github.com/rainfantry/release-blackops-skill</sub>
