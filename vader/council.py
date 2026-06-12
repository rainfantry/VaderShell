"""
VaderShell — the planning council.

WHY THIS EXISTS
---------------
You wanted two sets of eyes on a plan *before* committing to build it: Claude's
take AND Kimi's take, side by side, plus a read on where they agree and clash —
so you see "both sides of context" and *you* decide. This module runs that.

It is deliberately BOUNDED so it can never run away:
  - each model speaks exactly ONCE,
  - Claude compares the two takes exactly ONCE (the single "assess the other's
    input" round you asked for),
  - then it STOPS and hands control back to you.
No back-and-forth between models, no loops, no surprise costs.

THE FLOW
--------
  1. Ask Claude how it would approach the task   ->  yield ("claude", text)
  2. Ask Kimi the same task                       ->  yield ("kimi", text)
  3. Ask Claude to compare both plans for you      ->  yield ("synthesis", text)
  (then the caller shows you all three and waits)
"""

# 'os' reads environment variables (the OpenRouter key, the model name).
import os
# 'subprocess' runs the real `claude` CLI as a one-shot command.
import subprocess


# The wrapper we put around YOUR task when asking each model to PLAN (not build).
# We force a short, structured plan — approach, risks, steps — and explicitly
# forbid code, because this stage is about thinking, not typing.
_PLAN_PROMPT = (
    "You are planning, not building. For the task below, give a SHORT plan:\n"
    "- recommended approach (2-4 sentences)\n"
    "- the top 2 risks or unknowns\n"
    "- the steps, in order (brief)\n"
    "Do NOT write code yet.\n\nTASK:\n{task}"
)

# The wrapper for Claude's single comparison pass — it reads BOTH plans and tells
# you where they line up, where they fight, and what it'd do. This is the one
# "review" round; it never triggers another model turn.
_SYNTH_PROMPT = (
    "Two AI models each planned the same task. Compare them for the operator:\n"
    "- where they AGREE\n"
    "- where they DIFFER or conflict\n"
    "- one-line recommendation on how to proceed\n"
    "Be concise.\n\n"
    "TASK:\n{task}\n\n=== CLAUDE'S PLAN ===\n{claude}\n\n=== KIMI'S PLAN ===\n{kimi}"
)


def _ask_claude(prompt: str) -> str:
    """Get one planning answer from the real `claude` CLI.

    We run it in print mode (-p) with plain text output and NO tools — this stage
    is pure thinking, so the model just returns a plan. Running from your home
    directory means it still loads your CLAUDE.md + memory for context.
    """
    # Build and run the command, capturing its text output. encoding='utf-8'
    # so any em-dashes / unicode in the reply decode correctly on Windows.
    # Use the configured Claude model (the gateway sets Sonnet; the terminal
    # defaults to Opus). Lets the phone council run lighter than the desk one.
    model = os.environ.get("VADER_CLAUDE_MODEL", "").strip() or "claude-opus-4-8"
    # --dangerously-skip-permissions gives the council the SAME full kit as VADER's
    # individual channel: web search, bash, file tools, and your skills (loaded from
    # the home dir below). So it can actually go verify a claim or use a skill —
    # not just reason in a vacuum. Costs more + slower (it may take agentic steps).
    result = subprocess.run(
        ["claude", "-p", "--output-format", "text", "--model", model,
         "--dangerously-skip-permissions", prompt],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=os.path.expanduser("~"),
        timeout=300,
    )
    # Non-zero exit = the CLI failed; surface its error rather than returning junk.
    if result.returncode != 0:
        raise RuntimeError((result.stderr or "claude CLI error").strip()[:400])
    return result.stdout.strip()


def _ask_kimi(prompt: str) -> str:
    """Get one planning answer from Kimi (the second opinion) via OpenRouter."""
    # Imported here, not at the top, so the rest of the app runs even if the
    # openai package isn't installed.
    from openai import OpenAI

    # Kimi rides on OpenRouter, which needs this key in your environment / .env.
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set — Kimi can't weigh in.")
    # Which Kimi model to use (defaults to k2.5 if you haven't overridden it).
    model = os.environ.get("VADER_MODEL", "moonshotai/kimi-k2.5").strip()

    # An OpenAI-style client pointed at OpenRouter's endpoint.
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key)
    # One non-streamed chat completion — we just want the whole plan back.
    resp = client.chat.completions.create(
        model=model,
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    # Pull the reply text out of the response (guard against an empty one).
    return (resp.choices[0].message.content or "").strip()


def run_council(task: str):
    """Run the bounded planning council and yield each block as it finishes.

    Yields (label, text) pairs in this fixed order so the caller can label and
    print each as it arrives:
        ("claude", ...)    — Claude's plan
        ("kimi", ...)      — Kimi's plan
        ("synthesis", ...) — Claude comparing the two
    """
    # 1. Claude's plan.
    claude_take = _ask_claude(_PLAN_PROMPT.format(task=task))
    yield ("claude", claude_take)

    # 2. Kimi's plan (the independent second opinion).
    kimi_take = _ask_kimi(_PLAN_PROMPT.format(task=task))
    yield ("kimi", kimi_take)

    # 3. Claude reads BOTH and reports where they agree / clash — the one review
    #    round. After this, the function returns and control goes back to you.
    synthesis = _ask_claude(
        _SYNTH_PROMPT.format(task=task, claude=claude_take, kimi=kimi_take)
    )
    yield ("synthesis", synthesis)
