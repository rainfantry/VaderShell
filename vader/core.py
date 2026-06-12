"""
22DIV — agent core: the send-a-message / stream-the-reply engine.

This is the brain stem. Both the terminal chat (terminal.py) and the phone
gateways (next) call in here. It holds the running conversation and knows how to
talk to whichever provider auth.py picked.

For the **claude** path it drives the real `claude` CLI with full tools and
autonomy, and streams its events so you watch it think and act live. For
**kimi/openrouter** it's a plain streamed chat.

`stream_reply` yields **(kind, text)** pairs so the caller can style each kind:
  - "thinking"     → the model's reasoning (often just a "(thinking…)" beat)
  - "tool"         → an action it's taking (e.g. "Bash whoami")
  - "tool_result"  → the result of that action
  - "text"         → the actual answer
"""

import json
import os
import subprocess
import uuid

from .auth import AgentConfig, CLAUDE_CODE_SYSTEM_PREFIX

# Persona appended to whatever system prompt the brain already has. Kept light —
# on the claude path your full ~/CLAUDE.md + memory load underneath this.
_PERSONA = (
    "You are also VADER, George's personal survey-tech assistant running inside "
    "22DIV. Be direct, concise, and practical."
)

# Reply cap for the kimi/openrouter (non-CLI) paths. The CLI manages its own.
_MAX_TOKENS = 8000


class Agent:
    """Holds one ongoing conversation and streams replies as (kind, text) pairs."""

    def __init__(self, config: AgentConfig):
        # The resolved brain (provider, model, client, auth kind).
        self.cfg = config
        # Running history (used by the kimi/openrouter paths; the CLI keeps its
        # own history via its session id).
        self.messages: list[dict] = []
        # claude-CLI session id so the CLI keeps context across turns.
        self._cli_session_id = str(uuid.uuid4())
        self._cli_started = False

    def _system_prompt(self) -> str:
        """System prompt for the non-CLI paths. The OAuth API path must lead with
        the Claude-Code line; everyone else just gets the persona."""
        if self.cfg.needs_cc_prefix:
            return f"{CLAUDE_CODE_SYSTEM_PREFIX}\n\n{_PERSONA}"
        return _PERSONA

    def reset(self) -> None:
        """Forget the conversation and start fresh (new CLI session too)."""
        self.messages = []
        self._cli_session_id = str(uuid.uuid4())
        self._cli_started = False

    def stream_reply(self, user_text: str):
        """Add the user's message, stream the reply as (kind, text) pairs, then
        remember the final answer so the next turn has context."""
        self.messages.append({"role": "user", "content": user_text})
        full: list[str] = []  # collects the answer text to store afterwards

        if self.cfg.kind == "claude_cli":
            # Real `claude` CLI — full tools, autonomy, your loaded context.
            yield from self._stream_claude_cli(user_text, full)

        elif self.cfg.kind in ("anthropic_oauth", "anthropic_key"):
            # Direct Anthropic API (the token path — kept as an option).
            with self.cfg.client.messages.stream(
                model=self.cfg.model,
                max_tokens=_MAX_TOKENS,
                system=self._system_prompt(),
                messages=self.messages,
            ) as stream:
                for chunk in stream.text_stream:
                    full.append(chunk)
                    yield ("text", chunk)

        else:
            # OpenAI-compatible (Kimi / OpenRouter) — plain chat, no tools.
            msgs = [{"role": "system", "content": self._system_prompt()}, *self.messages]
            stream = self.cfg.client.chat.completions.create(
                model=self.cfg.model,
                max_tokens=_MAX_TOKENS,
                messages=msgs,
                stream=True,
            )
            for event in stream:
                delta = event.choices[0].delta.content if event.choices else None
                if delta:
                    full.append(delta)
                    yield ("text", delta)

        # Remember the assistant's answer so the conversation stays coherent.
        self.messages.append({"role": "assistant", "content": "".join(full)})

    def _stream_claude_cli(self, user_text: str, full: list[str]):
        """Drive the real `claude` binary with full tools + autonomy, parsing its
        streamed JSON events into (kind, text) pairs as they arrive.

        Runs in your home directory so it loads your full `~/CLAUDE.md`, memory,
        and skills — VADER inherits your entire Claude Code brain.
        """
        cmd = [
            "claude", "-p",
            "--output-format", "stream-json", "--verbose",
            "--dangerously-skip-permissions",          # full autonomy (your call)
            "--append-system-prompt", _PERSONA,
        ]
        # Pin the model only when it's actually a Claude model.
        if self.cfg.model.startswith("claude"):
            cmd += ["--model", self.cfg.model]
        # First turn creates the session; later turns resume it for memory.
        cmd += (["--resume", self._cli_session_id] if self._cli_started
                else ["--session-id", self._cli_session_id])
        cmd.append(user_text)

        # Popen (not run) so we can read events as they stream in, live.
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",   # claude outputs UTF-8; decode as such (fixes em-dash mojibake)
            errors="replace",
            bufsize=1,
            cwd=os.path.expanduser("~"),  # load your CLAUDE.md + memory + skills
        )
        self._cli_started = True

        # Each line of stdout is one JSON event. Parse and translate to (kind,text).
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue  # ignore any non-JSON noise

            etype = ev.get("type")
            if etype == "assistant":
                # The model emitted content: thinking, a tool call, or answer text.
                for block in ev.get("message", {}).get("content", []):
                    bt = block.get("type")
                    if bt == "thinking":
                        text = (block.get("thinking") or "").strip()
                        yield ("thinking", text or "(thinking…)")
                    elif bt == "tool_use":
                        name = block.get("name", "tool")
                        inp = block.get("input", {}) or {}
                        detail = inp.get("command") or inp.get("description") or ""
                        yield ("tool", f"{name} {detail}".strip())
                    elif bt == "text":
                        text = block.get("text") or ""
                        if text:
                            full.append(text)
                            yield ("text", text)
            elif etype == "user":
                # A tool finished — surface a short slice of its result.
                for block in ev.get("message", {}).get("content", []):
                    if block.get("type") == "tool_result":
                        res = block.get("content")
                        if isinstance(res, str) and res.strip():
                            yield ("tool_result", res.strip()[:200])

        proc.wait()
        if proc.returncode != 0:
            err = (proc.stderr.read() or "").strip()
            raise RuntimeError(err[:500] or "claude CLI error")
