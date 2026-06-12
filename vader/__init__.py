"""
VaderShell — a lean terminal + Discord AI agent that wraps the Claude CLI.

The `vader` package is the whole brain:
  - banner.py          : the startup logo (looks only)
  - auth.py            : picks the provider + credentials
  - core.py            : the conversation + streaming engine (drives `claude`)
  - terminal.py        : the interactive terminal chat (the launcher opens this)
  - gateway_discord.py : the Discord bot front door

The Claude path shells out to the real `claude` CLI, so it inherits your logged-in
Claude Code session — full tools, your CLAUDE.md, your skills. No API token needed.
"""

__version__ = "0.1.0"
