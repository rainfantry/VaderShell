"""
22DIV — interactive terminal chat. This is what the `22div` alias opens.

Paints the branded banner, then runs a simple read–reply loop: you type, VADER
streams an answer, repeat. `/reset` clears the chat, `/exit` quits.
"""

# 'sys' is used to exit cleanly with an error code if startup fails.
import sys
# 'Path' lets us find the .env next to this package no matter where you run from.
from pathlib import Path
# python-dotenv loads that .env file (where your token lives) into the environment.
from dotenv import load_dotenv
# rich's Console gives us styled prompts and output.
from rich.console import Console

# Our own pieces: the banner art, the auth resolver, the agent engine, and the
# two-model planning council.
from . import banner
from .auth import resolve
from .core import Agent
from .council import run_council

# One shared Console for the whole session.
_console = Console()


def main() -> None:
    """Entry point — the alias / launcher calls this."""
    # Load the project's .env (token, provider choice) into the environment so
    # auth.resolve() can see it. We point at the .env beside this package so it
    # works no matter which folder you launched the alias from.
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")

    # 1. Work out which brain + credentials to use. If anything's missing,
    #    resolve() raises a clear, fix-it error instead of failing cryptically.
    try:
        cfg = resolve()
    except Exception as e:
        _console.print(f"[bold red]Startup failed:[/] {e}")
        sys.exit(1)

    # 2. Paint the 22DIV / VADER banner, showing the live provider + model so you
    #    can confirm at a glance which brain answered the bell.
    banner.print_banner(model=cfg.model, provider=cfg.provider)

    # 3. Build the agent — it holds the running conversation.
    agent = Agent(cfg)

    _console.print("[dim]Type your message.  /reset clears the chat,  /exit quits.[/]\n")

    # 4. The read–reply loop. Runs until you quit.
    while True:
        try:
            # Styled prompt; input() blocks until you press Enter.
            user = _console.input("[bold #FFD700]you ›[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            # Ctrl-D / Ctrl-C → quit cleanly without a stack trace.
            _console.print("\n[dim]— signing off —[/]")
            break

        # Ignore empty lines.
        if not user:
            continue
        # Quit commands.
        if user in ("/exit", "/quit"):
            _console.print("[dim]— signing off —[/]")
            break
        # Clear the conversation.
        if user == "/reset":
            agent.reset()
            _console.print("[dim]— conversation cleared —[/]\n")
            continue
        # /plan <task> → convene the council: Claude's plan, Kimi's plan, and
        # Claude comparing the two. One bounded round, then it waits for you.
        if user.startswith("/plan "):
            task = user[len("/plan "):].strip()
            _console.print("[bold]— planning council: two minds, one task —[/]\n")
            _labels = {"claude": ("CLAUDE", "#E24B4A"),
                       "kimi": ("KIMI", "#63991F"),
                       "synthesis": ("SYNTHESIS", "#FFC400")}
            try:
                for label, text in run_council(task):
                    name, colour = _labels.get(label, (label.upper(), ""))
                    _console.print(name + ":", style=f"bold {colour}", highlight=False)
                    _console.print(text, markup=False, highlight=False)
                    _console.print()
            except Exception as e:
                _console.print(f"[bold red]council error:[/] {e}")
            _console.print("[dim]Two sides on the table — your call. Give a task to build, or refine.[/]\n")
            continue

        # Stream the agent's work: thinking, each tool call + result, and the
        # answer — each kind styled differently so you watch it think and act.
        _console.print("[bold #CD7F32]vader ›[/]")
        try:
            for kind, text in agent.stream_reply(user):
                if kind == "thinking":
                    _console.print("  💭 " + text, style="dim italic", markup=False, highlight=False)
                elif kind == "tool":
                    _console.print("  ⚙ " + text, style="#FFBF00", markup=False, highlight=False)
                elif kind == "tool_result":
                    _console.print("  ✓ " + text, style="dim", markup=False, highlight=False)
                else:  # "text" — the actual answer
                    _console.print(text, end="", markup=False, highlight=False)
        except Exception as e:
            # A 429 means authenticated-but-throttled — calm message, not a traceback.
            msg = str(e)
            if "429" in msg or "rate_limit" in msg.lower():
                _console.print(
                    "\n[bold yellow]⚠ rate limited[/] — Max usage replenishing. "
                    "Switch brains in .env (VADER_PROVIDER=kimi/openrouter) to keep going."
                )
            else:
                _console.print(f"\n[bold red]error:[/] {e}")
        # Blank line after each reply.
        _console.print("\n")


# Allows running it directly during development with: python -m vader.terminal
if __name__ == "__main__":
    main()
