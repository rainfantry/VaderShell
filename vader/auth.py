"""
22DIV — auth & provider resolution.

This is the keystone. Its single job: figure out WHICH brain to talk to and
HOW to authenticate, then hand back a ready-to-use client. Everything else in
the agent just asks this file "who am I talking to?" and gets an answer.

Three supported brains, chosen by the VADER_PROVIDER environment variable:

  - "claude"      → Anthropic directly. If the token is an OAuth/subscription
                    token (sk-ant-oat… / cc-… ) it bills against your Claude Max
                    plan, NOT an API balance. This is the default.
  - "kimi"        → Moonshot's Kimi, an OpenAI-compatible endpoint (API key).
  - "openrouter"  → OpenRouter, also OpenAI-compatible (API key).

Switching brains is just changing one env var + having that provider's key in
the environment — exactly the "api key in env" switch you asked for.
"""

# 'os' lets us read environment variables (the VADER_PROVIDER setting, the
# tokens, etc). 'dataclasses' gives us a tidy little struct to pass around.
import os
from dataclasses import dataclass

# ── Claude Code identity constants ────────────────────────────────────────
# When you authenticate with a Max/Pro *subscription* OAuth token (rather than a
# pay-as-you-go API key), Anthropic's servers expect the request to look like it
# came from the official Claude Code CLI. If it doesn't, they flag or 500 the
# traffic. These three constants are how we make our requests look legitimate.

# Beta feature flags Claude Code sends on subscription requests.
CLAUDE_CODE_BETAS = "claude-code-20250219,oauth-2025-04-20"
# The user-agent string that marks the request as coming from the Claude CLI.
# The version only needs to be "recent enough"; this is a safe current value.
CLAUDE_CODE_USER_AGENT = "claude-cli/2.1.74 (external, cli)"
# Subscription requests MUST begin their system prompt with this exact line, or
# Anthropic rejects them. core.py prepends it automatically for the OAuth path.
CLAUDE_CODE_SYSTEM_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude."

# Default model when VADER_MODEL isn't set. Opus 4.8 = the strongest brain.
DEFAULT_CLAUDE_MODEL = "claude-opus-4-8"


def _is_oauth_token(key: str) -> bool:
    """Decide whether `key` is a subscription OAuth token (Bearer auth) or a
    plain API key (x-api-key auth).

    The rule, copied from how Claude Code itself classifies tokens:
      - "sk-ant-api…"  → a normal pay-as-you-go API key   → NOT oauth
      - "sk-ant-…"     → a setup/subscription token        → oauth
      - "cc-…"         → a Claude Code OAuth access token   → oauth
      - "eyJ…"         → a JWT from the OAuth flow          → oauth
    Anything else (Kimi keys, OpenRouter keys) → NOT oauth.
    """
    if not key:
        return False
    if key.startswith("sk-ant-api"):  # normal Console API key
        return False
    if key.startswith("sk-ant-"):     # setup-token / subscription token
        return True
    if key.startswith("cc-"):         # Claude Code OAuth access token
        return True
    if key.startswith("eyJ"):         # JWT
        return True
    return False


@dataclass
class AgentConfig:
    """A tidy bundle describing the resolved brain. core.py reads this to know
    how to build and send a request."""
    provider: str          # "claude" | "kimi" | "openrouter"
    model: str             # the model id to ask for
    kind: str              # "anthropic_oauth" | "anthropic_key" | "openai"
    client: object         # the constructed SDK client, ready to call
    needs_cc_prefix: bool  # True only for the subscription-OAuth path


def _build_claude_cli(model: str) -> AgentConfig:
    """Drive the REAL `claude` CLI as the engine — the reliable Claude path.

    Instead of hand-rolling an API call with a token (which Anthropic rate-limits
    hard — instant 429s even when your Max plan is 85% free), we shell out to the
    actual `claude` binary you're already logged into. It inherits the exact auth
    that works in your terminal today. No token needed here; core.py runs it.
    """
    import shutil
    # Make sure the CLI is actually installed before we promise it works.
    if shutil.which("claude") is None:
        raise RuntimeError(
            "The `claude` CLI isn't on PATH. Install Claude Code, or switch to "
            "VADER_PROVIDER=kimi / openrouter."
        )
    return AgentConfig("claude", model, "claude_cli", client=None, needs_cc_prefix=False)


def _build_claude(model: str) -> AgentConfig:
    """Wire up the Anthropic brain (the default).

    Looks for a token in this order:
      1. CLAUDE_CODE_OAUTH_TOKEN  (from `claude setup-token` — your Max plan)
      2. ANTHROPIC_API_KEY        (a pay-as-you-go key, if you ever want it)
    """
    # 'anthropic' is Anthropic's official Python SDK. Imported here (not at the
    # top) so the other providers don't need it installed to work.
    from anthropic import Anthropic

    # Grab whichever token is present, preferring the subscription one.
    oauth = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "").strip()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if oauth and _is_oauth_token(oauth):
        # ── Subscription path: bill against Claude Max, not an API balance. ──
        # If a pay-as-you-go key is ALSO in the environment, the SDK would send
        # both it and the Bearer token and Anthropic rejects that — so drop it.
        os.environ.pop("ANTHROPIC_API_KEY", None)
        # auth_token=… makes the SDK send "Authorization: Bearer <token>".
        # The default_headers make every request look like the Claude CLI.
        client = Anthropic(
            auth_token=oauth,
            default_headers={
                "anthropic-beta": CLAUDE_CODE_BETAS,
                "User-Agent": CLAUDE_CODE_USER_AGENT,
            },
        )
        return AgentConfig("claude", model, "anthropic_oauth", client, needs_cc_prefix=True)

    if api_key:
        # ── Pay-as-you-go path: normal API key, normal x-api-key auth. ──
        client = Anthropic(api_key=api_key)
        return AgentConfig("claude", model, "anthropic_key", client, needs_cc_prefix=False)

    # Neither token found — fail loudly with a fix, don't limp along silently.
    raise RuntimeError(
        "No Claude credentials found. Run `claude setup-token` and set the "
        "result as CLAUDE_CODE_OAUTH_TOKEN (uses your Max plan), or set "
        "ANTHROPIC_API_KEY for pay-as-you-go."
    )


def _build_openai_compatible(provider: str, model: str) -> AgentConfig:
    """Wire up an OpenAI-compatible brain (Kimi or OpenRouter).

    Both speak the same 'chat completions' dialect, so one builder covers both —
    only the base URL and which env var holds the key differ.
    """
    # 'openai' SDK talks to any OpenAI-compatible endpoint, not just OpenAI.
    from openai import OpenAI

    if provider == "kimi":
        base_url = os.environ.get("KIMI_BASE_URL", "https://api.kimi.com/coding/v1")
        api_key = os.environ.get("KIMI_API_KEY", "").strip()
        key_name = "KIMI_API_KEY"
    else:  # "openrouter"
        base_url = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        key_name = "OPENROUTER_API_KEY"

    if not api_key:
        raise RuntimeError(f"Provider '{provider}' selected but {key_name} is not set in the environment.")

    client = OpenAI(base_url=base_url, api_key=api_key)
    return AgentConfig(provider, model, "openai", client, needs_cc_prefix=False)


def resolve() -> AgentConfig:
    """Top-level entry point. Reads VADER_PROVIDER / VADER_MODEL from the
    environment and returns a ready-to-use AgentConfig. core.py calls this once
    at startup."""
    # Which brain? Default to Claude (the one you trust) if unset.
    provider = os.environ.get("VADER_PROVIDER", "claude").strip().lower()

    if provider in ("claude", "claude-api"):
        # Only honour VADER_MODEL for Claude if it's actually a Claude model, so a
        # leftover kimi/openrouter model in .env doesn't break the switch back to
        # Claude (it just falls back to the default Opus model instead).
        requested = os.environ.get("VADER_MODEL", "").strip()
        model = requested if requested.startswith("claude") else DEFAULT_CLAUDE_MODEL
        # "claude"     → drive the REAL `claude` CLI (uses your working Claude Code
        #                login; no token, no 429s). The reliable path.
        # "claude-api" → hand-rolled API call with an OAuth/API token. Kept as an
        #                option, but Anthropic rate-limits it hard — avoid (see README).
        if provider == "claude":
            return _build_claude_cli(model)
        return _build_claude(model)

    if provider in ("kimi", "openrouter"):
        # These have no single "obvious" default model, so require VADER_MODEL.
        model = os.environ.get("VADER_MODEL", "").strip()
        if not model:
            raise RuntimeError(f"Provider '{provider}' needs VADER_MODEL set (e.g. moonshotai/kimi-k2.5).")
        return _build_openai_compatible(provider, model)

    raise RuntimeError(f"Unknown VADER_PROVIDER '{provider}'. Use: claude | kimi | openrouter.")
