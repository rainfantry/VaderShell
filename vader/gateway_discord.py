"""
22DIV — Discord gateway.

Turns VADER into a Discord bot: your messages get answered by the SAME
`core.Agent` the terminal uses (full Claude + tools + your memory).

Coalition mode: in a designated SERVER (or channel), a second bot (Kimi /
SERVITOR) answers you, and VADER reads what it said and adds a second opinion.
One-directional — VADER reads the peer; the peer is blind to VADER — so it can't
loop. (Safety rests on the peer ignoring bots; a cooldown is the backup.)

Peer bots usually STREAM by editing one message ("Thinking… 0%" → partial → final),
so VADER waits for the message to stop changing (debounce) and only then reads the
FINAL text — never the placeholder or a half-written partial.

Everything is logged to `gateway.log` (and the terminal) for review.

Run with:  python -m vader.gateway_discord
"""

import asyncio
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

import discord

from .auth import resolve
from .core import Agent
from .council import run_council, _ask_claude

# ── Logging — every event to gateway.log AND the terminal. ──
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

# How long the peer message must go UNCHANGED before we treat it as final.
_SETTLE_SECONDS = 5

# Branded banner written to the log + terminal at startup.
_BANNER = (
    "\n██████╗ ██████╗ ██████╗ ██╗██╗   ██╗\n"
    "╚════██╗╚════██╗██╔══██╗██║██║   ██║\n"
    " █████╔╝ █████╔╝██║  ██║██║██║   ██║\n"
    "██╔═══╝ ██╔═══╝ ██║  ██║██║╚██╗ ██╔╝\n"
    "███████╗███████╗██████╔╝██║ ╚████╔╝\n"
    "╚══════╝╚══════╝╚═════╝ ╚═╝  ╚═══╝\n"
    "   VADER · survey-tech command channel · george wu"
)


def _split(text: str):
    text = text or "(no output)"
    while text:
        yield text[:_DISCORD_LIMIT]
        text = text[_DISCORD_LIMIT:]


def _run_turn(agent: Agent, prompt: str) -> str:
    actions, answer = [], []
    for kind, text in agent.stream_reply(prompt):
        if kind == "tool":
            actions.append(f"⚙ {text}")
        elif kind == "text":
            answer.append(text)
    out = ""
    if actions:
        out += "\n".join(actions) + "\n\n"
    return (out + "".join(answer)).strip()


def _in_coalition(message) -> bool:
    guild_id = str(message.guild.id) if message.guild else ""
    chan_id = str(message.channel.id)
    return bool((_COALITION_SERVER and guild_id == _COALITION_SERVER)
                or (_COALITION_CHANNEL and chan_id == _COALITION_CHANNEL))


def _is_peer(message) -> bool:
    """The coalition peer bot (Kimi/SERVITOR) inside the coalition scope."""
    return bool(message.author.bot and _in_coalition(message)
                and (not _PEER_BOT_ID or str(message.author.id) == _PEER_BOT_ID))


# Markers that flag a peer message as status / housekeeping (a progress bar, a
# "Thinking…" placeholder, a Hermes self-improvement notice) rather than an
# actual answer to you. We never burn a second opinion on these.
_STATUS_MARKERS = ("Thinking", "thinking", "Self-improvement", "review:", "💾", "⚕", "⏳", "🔄")


def _is_settled(text: str) -> bool:
    """True only when the peer's message looks like a FINAL answer — not a progress
    placeholder, not a half-streamed partial, and not Hermes housekeeping spam."""
    t = (text or "").strip()
    if not t:
        return False
    if any(m in t for m in _STATUS_MARKERS):   # placeholder / status / housekeeping
        return False
    if t.endswith("▉") or t.endswith("█") or t.endswith("…"):  # streaming cursor
        return False
    if len(t) < 15:                            # too short to be a real answer yet
        return False
    return True


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

    _last_op = {"t": 0.0}      # cooldown net for second-opinions
    _debounce: dict = {}        # peer message id -> pending settle task

    async def _do_second_opinion(peer_message, kimi_said: str) -> None:
        now = time.monotonic()
        if now - _last_op["t"] < 8:
            log.info("second-opinion skipped (cooldown)")
            return
        _last_op["t"] = now
        # The operator's most recent message here — what the peer answered.
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
        """(Re)start the settle timer for this peer message. Every create/edit
        cancels the prior timer, so we only fire once the peer STOPS editing."""
        mid = peer_message.id
        old = _debounce.get(mid)
        if old:
            old.cancel()

        async def _settle():
            try:
                await asyncio.sleep(_SETTLE_SECONDS)
                # Re-fetch the message to get its final, fully-streamed content.
                fresh = await peer_message.channel.fetch_message(mid)
                content = (fresh.content or "").strip()
                if not _is_settled(content):
                    log.info("peer msg %s not settled (placeholder/partial) — skipping", mid)
                    return
                log.info("peer msg %s settled — firing second opinion", mid)
                await _do_second_opinion(fresh, content)
            except asyncio.CancelledError:
                pass  # superseded by a newer edit — expected
            except Exception as e:
                log.error("settle/fire failed: %s", e)
            finally:
                _debounce.pop(mid, None)

        _debounce[mid] = asyncio.create_task(_settle())

    @client.event
    async def on_ready():
        log.info("VADER online as %s | UID=%s", client.user, _ALLOWED_UID or "anyone")
        if os.environ.get("VADER_GATEWAY_TEST"):
            await client.close()

    @client.event
    async def on_message_edit(before, after):
        # Peer streams by editing — re-arm the settle timer on each edit so we
        # read the FINAL text, not the partial.
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

        # ── Coalition peer → schedule a settled second opinion (don't fire now). ──
        if _is_peer(message):
            log.info("peer create %s — arming settle timer", message.id)
            await _schedule(message)
            return
        if is_bot:
            log.info("ignoring bot %s (not coalition peer / out of scope)", message.author)
            return

        # ── Human message. ──
        if _ALLOWED_UID and str(message.author.id) != _ALLOWED_UID:
            log.info("ignoring non-operator %s", message.author)
            return
        if _ALLOWED_CHANNELS and chan_id not in _ALLOWED_CHANNELS:
            log.info("ignoring channel %s (not in allow-list)", chan_id)
            return
        if not content:
            return

        if content == "/reset":
            agent.reset()
            await message.channel.send("— conversation cleared —")
            log.info("conversation reset")
            return

        if content.startswith("/plan "):
            task = content[len("/plan "):].strip()
            log.info("council: /plan %r", task[:60])
            await message.channel.send("— planning council: two minds, one task —")
            try:
                blocks = await asyncio.to_thread(lambda: list(run_council(task)))
            except Exception as e:
                log.error("council failed: %s", e)
                await message.channel.send(f"council error: {e}")
                return
            heads = {"claude": "🟥 CLAUDE", "kimi": "🟩 KIMI", "synthesis": "🟨 SYNTHESIS"}
            for label, text in blocks:
                for chunk in _split(f"**{heads.get(label, label.upper())}**\n{text}"):
                    await message.channel.send(chunk)
            log.info("council posted")
            return

        log.info("answering operator")
        async with message.channel.typing():
            reply = await asyncio.to_thread(_run_turn, agent, content)
        for chunk in _split(reply):
            await message.channel.send(chunk)


    client.run(_TOKEN)


if __name__ == "__main__":
    main()
