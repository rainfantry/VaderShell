"""
22DIV — Discord gateway.

Turns VADER into a Discord bot: your messages get answered by the SAME
`core.Agent` the terminal uses (full Claude + tools + your memory).

Native slash commands (the `/` picker, shown under VADER):
  /help            — list the commands and what they do
  /plan <task>     — two-model planning council (Claude + Kimi + synthesis)
  /model <name>    — switch VADER's brain (opus|sonnet|haiku|kimi) and reboot onto it
  /reset           — clear VADER's conversation memory
  /restart         — reboot the gateway (supervised; reconnects in a few seconds)
(The same commands also work typed as plain text, as a fallback.)

Coalition mode: in a designated server/channel, a peer bot (Kimi/SERVITOR) answers
you and VADER reads its FINAL reply (after streaming settles, skipping placeholders)
and posts a second opinion. One-directional, so it can't loop.

Everything is logged to gateway.log (and the terminal). `/restart` exits 42 so the
supervisor launcher relaunches a fresh process.
"""

import asyncio
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
# Base config first...
load_dotenv(_ROOT / ".env")
# ...then any runtime override written by /model (wins over the launcher's model).
_OVERRIDE_FILE = _ROOT / "runtime_override.env"
if _OVERRIDE_FILE.exists():
    load_dotenv(_OVERRIDE_FILE, override=True)

import discord

from .auth import resolve
from .core import Agent
from .council import run_council, _ask_claude

# ── Logging ──
_LOG_PATH = _ROOT / "gateway.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(_LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
)
logging.getLogger("discord").setLevel(logging.WARNING)
log = logging.getLogger("vader.gateway")

_DISCORD_LIMIT = 1900

_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
_ALLOWED_UID = os.environ.get("VADER_DISCORD_UID", "").strip()
_ALLOWED_CHANNELS = {c.strip() for c in os.environ.get("VADER_DISCORD_CHANNEL_ID", "").split(",") if c.strip()}
_COALITION_SERVER = os.environ.get("VADER_COALITION_SERVER_ID", "").strip()
_COALITION_CHANNEL = os.environ.get("VADER_COALITION_CHANNEL_ID", "").strip()
_PEER_BOT_ID = os.environ.get("VADER_PEER_BOT_ID", "").strip()
_SETTLE_SECONDS = 5

# /model aliases → (provider, model).
_MODEL_ALIASES = {
    "opus":   ("claude", "claude-opus-4-8"),
    "sonnet": ("claude", "claude-sonnet-4-6"),
    "haiku":  ("claude", "claude-haiku-4-5"),
    "kimi":   ("kimi", "moonshotai/kimi-k2.5"),
}

_BANNER = (
    "\n██████╗ ██████╗ ██████╗ ██╗██╗   ██╗\n"
    "╚════██╗╚════██╗██╔══██╗██║██║   ██║\n"
    " █████╔╝ █████╔╝██║  ██║██║██║   ██║\n"
    "██╔═══╝ ██╔═══╝ ██║  ██║██║╚██╗ ██╔╝\n"
    "███████╗███████╗██████╔╝██║ ╚████╔╝\n"
    "╚══════╝╚══════╝╚═════╝ ╚═╝  ╚═══╝\n"
    "   VADER · survey-tech command channel · george wu"
)

_HELP = (
    "**VADER — commands**\n"
    "`/plan <task>` — two-model planning council: Claude plans, Kimi plans, Claude compares both.\n"
    "`/model <opus|sonnet|haiku|kimi>` — switch VADER's brain and reboot onto it.\n"
    "`/reset` — clear VADER's conversation memory (start fresh).\n"
    "`/restart` — reboot the gateway (reconnects in a few seconds).\n"
    "`/help` — this list.\n"
    "Otherwise, just message me — I answer with full tools, web search, and your memory."
)

_STATUS_MARKERS = ("Thinking", "thinking", "Self-improvement", "review:", "💾", "⚕", "⏳", "🔄")


def _split(text: str):
    text = text or "(no output)"
    while text:
        yield text[:_DISCORD_LIMIT]
        text = text[_DISCORD_LIMIT:]


def _run_turn(agent: Agent, prompt: str) -> str:
    log_lines, answer = [], []
    for kind, text in agent.stream_reply(prompt):
        if kind == "thinking":
            log_lines.append(f"💭 {text[:300]}")
        elif kind == "tool":
            log_lines.append(f"⚙ {text}")
        elif kind == "tool_result":
            log_lines.append(f"  ↳ {text[:150]}")
        elif kind == "text":
            answer.append(text)
    out = ""
    if log_lines:
        out += "\n".join(log_lines) + "\n\n"
    return (out + "".join(answer)).strip()


def _in_coalition(message) -> bool:
    guild_id = str(message.guild.id) if message.guild else ""
    chan_id = str(message.channel.id)
    return bool((_COALITION_SERVER and guild_id == _COALITION_SERVER)
                or (_COALITION_CHANNEL and chan_id == _COALITION_CHANNEL))


def _is_peer(message) -> bool:
    return bool(message.author.bot and _in_coalition(message)
                and (not _PEER_BOT_ID or str(message.author.id) == _PEER_BOT_ID))


def _is_settled(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if any(m in t for m in _STATUS_MARKERS):
        return False
    if t.endswith("▉") or t.endswith("█") or t.endswith("…"):
        return False
    if len(t) < 15:
        return False
    return True


def _write_model_override(provider: str, model: str) -> None:
    """Persist a runtime brain switch so it survives the reboot /model triggers."""
    lines = [f"VADER_PROVIDER={provider}"]
    lines.append(f"VADER_CLAUDE_MODEL={model}" if provider == "claude" else f"VADER_MODEL={model}")
    _OVERRIDE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    if not _TOKEN:
        raise SystemExit("DISCORD_BOT_TOKEN is not set in .env")

    agent = Agent(resolve())
    log.info(_BANNER)
    log.info("starting | coalition server=%s channel=%s peer=%s settle=%ss",
             _COALITION_SERVER or "-", _COALITION_CHANNEL or "-", _PEER_BOT_ID or "any-bot", _SETTLE_SECONDS)

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    tree = discord.app_commands.CommandTree(client)

    _last_op = {"t": 0.0}
    _debounce: dict = {}
    _restart = {"requested": False}

    def _is_operator(user_id) -> bool:
        return (not _ALLOWED_UID) or str(user_id) == _ALLOWED_UID

    # ── Coalition second-opinion (unchanged behaviour) ──
    async def _do_second_opinion(peer_message, kimi_said: str) -> None:
        now = time.monotonic()
        if now - _last_op["t"] < 8:
            log.info("second-opinion skipped (cooldown)")
            return
        _last_op["t"] = now
        question = ""
        async for m in peer_message.channel.history(limit=12, before=peer_message):
            if (not m.author.bot) and (not _ALLOWED_UID or str(m.author.id) == _ALLOWED_UID):
                question = (m.content or "").strip()
                break
        prompt = (
            "Another AI (Kimi) just answered the operator in a shared channel. Give a "
            "SHORT second opinion — agree, push back, or add what it missed. A few "
            "sentences, direct.\n\nOPERATOR ASKED:\n" + (question or "(unknown)") +
            "\n\nKIMI ANSWERED:\n" + kimi_said
        )
        try:
            async with peer_message.channel.typing():
                reply = await asyncio.to_thread(_ask_claude, prompt)
        except Exception as e:
            log.error("second-opinion failed: %s", e)
            return
        for chunk in _split("**🟥 VADER — second opinion**\n" + reply):
            await peer_message.channel.send(chunk)
        log.info("second-opinion posted")

    async def _schedule(peer_message) -> None:
        mid = peer_message.id
        old = _debounce.get(mid)
        if old:
            old.cancel()

        async def _settle():
            try:
                await asyncio.sleep(_SETTLE_SECONDS)
                fresh = await peer_message.channel.fetch_message(mid)
                content = (fresh.content or "").strip()
                if not _is_settled(content):
                    log.info("peer msg %s not settled — skipping", mid)
                    return
                log.info("peer msg %s settled — firing second opinion", mid)
                await _do_second_opinion(fresh, content)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.error("settle/fire failed: %s", e)
            finally:
                _debounce.pop(mid, None)

        _debounce[mid] = asyncio.create_task(_settle())

    async def _trigger_restart() -> None:
        _restart["requested"] = True
        log.info("restart requested by operator")
        await client.close()

    # ── Native slash commands ──
    @tree.command(name="help", description="List VADER's commands and what they do")
    async def _cmd_help(interaction):
        await interaction.response.send_message(_HELP, ephemeral=True)

    @tree.command(name="reset", description="Clear VADER's conversation memory")
    async def _cmd_reset(interaction):
        if not _is_operator(interaction.user.id):
            return await interaction.response.send_message("Not authorised.", ephemeral=True)
        agent.reset()
        log.info("conversation reset (slash)")
        await interaction.response.send_message("— conversation cleared —")

    @tree.command(name="restart", description="Reboot the VADER gateway")
    async def _cmd_restart(interaction):
        if not _is_operator(interaction.user.id):
            return await interaction.response.send_message("Not authorised.", ephemeral=True)
        await interaction.response.send_message("♻ restarting gateway — back in a few seconds…")
        await _trigger_restart()

    @tree.command(name="model", description="Switch VADER's brain and reboot (opus|sonnet|haiku|kimi)")
    @discord.app_commands.describe(name="opus, sonnet, haiku, or kimi")
    async def _cmd_model(interaction, name: str):
        if not _is_operator(interaction.user.id):
            return await interaction.response.send_message("Not authorised.", ephemeral=True)
        key = name.strip().lower()
        if key not in _MODEL_ALIASES:
            return await interaction.response.send_message(
                f"Unknown brain '{name}'. Use: opus, sonnet, haiku, kimi.", ephemeral=True)
        provider, model = _MODEL_ALIASES[key]
        _write_model_override(provider, model)
        log.info("model switch -> %s (%s) — rebooting", key, model)
        await interaction.response.send_message(f"♻ switching to **{key}** and rebooting…")
        await _trigger_restart()

    @tree.command(name="plan", description="Two-model planning council (Claude + Kimi)")
    @discord.app_commands.describe(task="what to plan")
    async def _cmd_plan(interaction, task: str):
        if not _is_operator(interaction.user.id):
            return await interaction.response.send_message("Not authorised.", ephemeral=True)
        await interaction.response.defer(thinking=True)  # council takes well over 3s
        log.info("council (slash): %r", task[:60])
        try:
            blocks = await asyncio.to_thread(lambda: list(run_council(task)))
        except Exception as e:
            log.error("council failed: %s", e)
            return await interaction.followup.send(f"council error: {e}")
        heads = {"claude": "🟥 CLAUDE", "kimi": "🟩 KIMI", "synthesis": "🟨 SYNTHESIS"}
        await interaction.followup.send("— planning council: two minds, one task —")
        for label, text in blocks:
            for chunk in _split(f"**{heads.get(label, label.upper())}**\n{text}"):
                await interaction.followup.send(chunk)
        log.info("council posted (slash)")

    @client.event
    async def on_ready():
        log.info("VADER online as %s | UID=%s", client.user, _ALLOWED_UID or "anyone")
        # Register the slash commands per-guild (instant, vs slow global propagation).
        try:
            n = 0
            for g in client.guilds:
                tree.copy_global_to(guild=g)
                await tree.sync(guild=g)
                n += 1
            log.info("slash commands synced to %d guild(s)", n)
        except Exception as e:
            log.error("slash sync failed: %s", e)
        if os.environ.get("VADER_GATEWAY_TEST"):
            await client.close()

    @client.event
    async def on_message_edit(before, after):
        if _is_peer(after):
            log.info("peer edit %s — re-arming settle timer", after.id)
            await _schedule(after)

    @client.event
    async def on_message(message):
        if client.user and message.author.id == client.user.id:
            return
        is_bot = message.author.bot
        guild_id = str(message.guild.id) if message.guild else "-"
        chan_id = str(message.channel.id)
        content = (message.content or "").strip()
        log.info("msg from %s bot=%s guild=%s ch=%s: %r", message.author, is_bot, guild_id, chan_id, content[:80])

        if _is_peer(message):
            log.info("peer create %s — arming settle timer", message.id)
            await _schedule(message)
            return
        if is_bot:
            return

        if _ALLOWED_UID and str(message.author.id) != _ALLOWED_UID:
            return
        if _ALLOWED_CHANNELS and chan_id not in _ALLOWED_CHANNELS:
            return
        if not content:
            return

        # Text-command fallbacks (so they work even before slash commands sync).
        if content == "/reset":
            agent.reset()
            await message.channel.send("— conversation cleared —")
            return
        if content == "/restart":
            await message.channel.send("♻ restarting gateway — back in a few seconds…")
            await _trigger_restart()
            return
        if content == "/help":
            await message.channel.send(_HELP)
            return
        if content.startswith("/plan "):
            task = content[len("/plan "):].strip()
            await message.channel.send("— planning council: two minds, one task —")
            try:
                blocks = await asyncio.to_thread(lambda: list(run_council(task)))
            except Exception as e:
                await message.channel.send(f"council error: {e}")
                return
            heads = {"claude": "🟥 CLAUDE", "kimi": "🟩 KIMI", "synthesis": "🟨 SYNTHESIS"}
            for label, text in blocks:
                for chunk in _split(f"**{heads.get(label, label.upper())}**\n{text}"):
                    await message.channel.send(chunk)
            return

        # Normal chat.
        log.info("answering operator")
        async with message.channel.typing():
            reply = await asyncio.to_thread(_run_turn, agent, content)
        for chunk in _split(reply):
            await message.channel.send(chunk)

    client.run(_TOKEN)
    if _restart["requested"]:
        log.info("exiting (code 42) for supervisor restart")
        raise SystemExit(42)


if __name__ == "__main__":
    main()
