"""
22DIV — terminal banner / branding.

This file's only job is to paint the "22DIV / VADER" logo and a one-line status
header when the agent starts. It talks to nothing and decides nothing — pure
cosmetics, kept separate on purpose so the look can change without ever
touching the brains of the agent.
"""

# 'rich' is the library that lets us print coloured, styled text in the
# terminal (the gold gradient on the logo, the dim grey subtitle, and so on).
from rich.console import Console
from rich.text import Text

# Make ONE shared Console object and print everything through it. Creating it
# once here and reusing it is tidier than spinning up a new one each call.
_console = Console()

# The big block-letter "22DIV" logo, one string per row. These are drawn with
# Unicode "box drawing" characters (the solid ██ blocks) in the same
# ANSI-Shadow style as the original Hermes logo — just spelling your name.
_LOGO_ROWS = [
    "██████╗ ██████╗ ██████╗ ██╗██╗   ██╗",
    "╚════██╗╚════██╗██╔══██╗██║██║   ██║",
    " █████╔╝ █████╔╝██║  ██║██║██║   ██║",
    "██╔═══╝ ██╔═══╝ ██║  ██║██║╚██╗ ██╔╝",
    "███████╗███████╗██████╔╝██║ ╚████╔╝ ",
    "╚══════╝╚══════╝╚═════╝ ╚═╝  ╚═══╝  ",
]

# The colour for each logo row, top to bottom — a gold→amber→bronze fade.
# (Hex colours: FFD700 = gold, FFBF00 = amber, CD7F32 = bronze.)
_LOGO_COLORS = ["#FFD700", "#FFD700", "#FFBF00", "#FFBF00", "#CD7F32", "#CD7F32"]


def print_banner(model: str = "", provider: str = "") -> None:
    """Paint the startup banner.

    `model` and `provider` are optional bits of text shown under the logo so you
    can see at a glance which brain is wired up (e.g. "claude · claude-opus-4-8").
    Pass nothing and that line is simply skipped.
    """
    # Blank line first so the logo isn't jammed against whatever came before.
    _console.print()

    # Walk each logo row alongside its matching colour and print them together.
    # `zip` pairs row[0] with colour[0], row[1] with colour[1], and so on.
    for row, colour in zip(_LOGO_ROWS, _LOGO_COLORS):
        _console.print(Text(row, style=f"bold {colour}"))

    # Your callsign under the logo, in bold gold.
    _console.print(Text("            V A D E R", style="bold #FFD700"))
    # The operator / tagline line, in quieter bronze so it sits below the name.
    _console.print(Text("   survey-tech command channel — george wu", style="#CD7F32"))

    # If we were told which model/provider is live, show it in dim grey. The
    # join just glues the non-empty pieces together with a " · " separator.
    if model or provider:
        bits = " · ".join(b for b in (provider, model) if b)
        _console.print(Text(f"   ⟢ {bits}", style="dim"))

    # Trailing blank line so the first chat prompt has room to breathe.
    _console.print()
