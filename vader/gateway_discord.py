"""
22DIV — Discord gateway.

Turns VADER into a Discord bot: your messages get answered by the SAME
`core.Agent` the terminal uses (full Claude + tools + your memory). This is the
"delegate from your phone" front door.

Run with:  python -m vader.gateway_discord   (or the gateway launcher .ps1)
It stays running and listens until you Ctrl-C it.
"""

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env (token, UID, provider choice) from the project root first.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import discord  # imported after load_dotenv so a missing dep error is obvious

from .auth import resolve
from .core import Agent

# Discord rejects messages over 2000 chars; we split a touch under that.
_DISCORD_LIMIT = 1900

# The bot token, and the single user allowed to command VADER (you).
_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
_ALLOWED_UID = os.environ.get("VADER_DISCORD_UID", "").strip()


def _split(text: str):
    """Yield the reply in Discord-sized chunks."""
    text = text or "(no output)"
    while text:
        yield text[:_DISCORD_LIMIT]
        text = text[_DISCORD_LIMIT:]


def _run_turn(agent: Agent, prompt: str) -> str:
    """Run one VADER turn (blocking — drives the claude CLI). Returns a single
    string: a short log of any tools it ran, then the answer."""
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


def main() -> None:
    if not _TOKEN:
        raise SystemExit("DISCORD_BOT_TOKEN is not set in .env")

    # One agent = one ongoing conversation (your personal assistant).
    agent = Agent(resolve())

    # message_content intent is REQUIRED to read what you type — make sure it's
    # toggled on in the Discord dev portal (Bot → Privileged Gateway Intents).
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"VADER online as {client.user} — listening to UID: {_ALLOWED_UID or 'anyone'}", flush=True)
        # Connection self-test: with VADER_GATEWAY_TEST=1, confirm login then exit.
        if os.environ.get("VADER_GATEWAY_TEST"):
            await client.close()

    @client.event
    async def on_message(message):
        # Never react to itself or other bots (prevents loops).
        if message.author.bot:
            return
        # Obey only you, when a UID is set.
        if _ALLOWED_UID and str(message.author.id) != _ALLOWED_UID:
            return
        content = (message.content or "").strip()
        if not content:
            return
        # Simple command: clear the conversation.
        if content == "/reset":
            agent.reset()
            await message.channel.send("— conversation cleared —")
            return
        # Show "typing…" while the blocking turn runs in a worker thread, so the
        # bot's event loop stays responsive.
        async with message.channel.typing():
            reply = await asyncio.to_thread(_run_turn, agent, content)
        for chunk in _split(reply):
            await message.channel.send(chunk)

    client.run(_TOKEN)


if __name__ == "__main__":
    main()
