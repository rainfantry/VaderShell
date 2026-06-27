"""
22DIV — agent core: the send-a-message / stream-the-reply engine.

This is the brain stem. Both the terminal chat (terminal.py) and the phone
gateways (next) call in here. It holds the running conversation and knows how to
talk to whichever provider auth.py picked.

For the **claude** path it drives the real `claude` CLI with full tools and
autonomy, and streams its events so you watch it think and act live. The
**kimi/openrouter** path is also a tool-using agent now (see tools.py): it runs
terminal commands, searches the web, and reads/writes files in a tool-call loop.

`stream_reply` yields **(kind, text)** pairs so the caller can style each kind:
  - "thinking"     → the model's reasoning (often just a "(thinking…)" beat)
  - "tool"         → an action it's taking (e.g. "Bash whoami")
  - "tool_result"  → the result of that action
  - "text"         → the actual answer
"""

import base64
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

# Hard cap on tool-call rounds in one turn. Dev work (build/test/fix) eats steps,
# so this is generous — it's only a runaway-loop backstop, not a normal limit.
_MAX_TOOL_STEPS = 40

# Extra system guidance for the kimi/openrouter path now that it has a tool belt.
# (The claude-CLI path doesn't need this — it IS Claude Code, with its own tools.)
# {workspace} is filled in at runtime from tools.WORKSPACE.
_TOOLS_SYSTEM = (
    "You are a fully autonomous software-dev agent on George's Windows 11 machine with a real "
    "tool belt: run_terminal (PowerShell/cmd/bash), web_search, fetch_url, read_file, write_file, "
    "list_dir, screenshot_desktop, screenshot_url, remember, recall, save_skill, use_skill, "
    "list_skills.\n\n"
    "WORKSPACE: your working directory is {workspace}. run_terminal runs there and relative file "
    "paths resolve there. Clone, create and build repos inside it. `cd` into a repo folder (or pass "
    "its path) before git commands.\n\n"
    "WHAT YOU CAN DO: commands inherit George's logged-in gh/git auth, PATH and environment. So you "
    "can clone and push PRIVATE repos, create new ones with `gh repo create <name> --private`, commit "
    "and push, drive the gh CLI, build/run/test projects (npm, dotnet, python…), and install packages. "
    "When building a web app, start its dev server with run_terminal, then screenshot_url "
    "http://localhost:<port> to SEE it rendered (the image is shown back to you) — fix and re-shoot "
    "until it's right.\n\n"
    "LEARNING (persists across restarts): you have long-term memory and skills. When George tells you "
    "to remember something or you learn a lasting preference, call remember(). When you work out a "
    "reusable workflow worth keeping, call save_skill(name, description, steps). Before doing a task you "
    "already have a skill for, call use_skill(name) to load its steps and follow them. Your current "
    "memory and skill list are shown to you below the rules.\n\n"
    "HOW TO WORK: ACT, don't just advise — when a task needs the machine, CALL the tools. Chain them. "
    "Verify by actually running/building/testing and reading the output (and screenshotting UIs); only "
    "claim done once it truly is. If a command fails, read the error and fix it — don't guess.\n\n"
    "GIT RULES: branch before risky work; never force-push; never commit secrets; NEVER add Claude/AI "
    "attribution or co-author lines to commits — all work is George's. Use shell='cmd' for python/node "
    "scripts (PowerShell mangles some quoting). Be deliberate with destructive commands. Keep chat "
    "replies tight."
)


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
        # Screenshots captured this round, fed back to the model as images so it
        # can SEE them. Off only if VADER_VISION=0 (the model must be multimodal).
        self._pending_images: list[str] = []
        self._vision = os.environ.get("VADER_VISION", "1").strip() != "0"

    def _system_prompt(self) -> str:
        """System prompt for the non-CLI paths. The OAuth API path must lead with
        the Claude-Code line; everyone else just gets the persona."""
        if self.cfg.needs_cc_prefix:
            return f"{CLAUDE_CODE_SYSTEM_PREFIX}\n\n{_PERSONA}"
        # The OpenAI-compatible path (Kimi/OpenRouter) now wields tools — tell it so,
        # and pin its identity: Kimi K2 loves to claim it's Claude/GPT, so state the
        # real model explicitly (built dynamically from the resolved brain).
        if self.cfg.kind == "openai":
            from . import tools  # for the live workspace path
            identity = (
                f"Your identity: you are VADER, running on the '{self.cfg.model}' model "
                f"via the {self.cfg.provider} API. You are NOT Claude, Anthropic, GPT, or "
                f"OpenAI — never claim to be. If asked what model or AI you are, say you "
                f"are VADER on Kimi ({self.cfg.model})."
            )
            tools_system = _TOOLS_SYSTEM.format(workspace=tools.WORKSPACE)
            # Fold in persistent memory + the learned-skills index, read fresh from
            # disk each turn — so anything saved is live next message AND after restart.
            learned = ""
            mem = tools.memory_text()
            if mem:
                learned += ("\n\nLONG-TERM MEMORY (persists across restarts — treat as known facts):\n"
                            + mem)
            idx = tools.skills_index()
            if idx:
                learned += ("\n\nSKILLS YOU'VE LEARNED (call use_skill(name) to load the full steps "
                            "before doing a matching task):\n" + idx)
            return f"{_PERSONA}\n\n{identity}\n\n{tools_system}{learned}"
        return _PERSONA

    def reset(self) -> None:
        """Forget the conversation and start fresh (new CLI session too)."""
        self.messages = []
        self._cli_session_id = str(uuid.uuid4())
        self._cli_started = False
        self._pending_images = []

    def stream_reply(self, user_text: str):
        """Add the user's message, stream the reply as (kind, text) pairs, then
        remember the final answer so the next turn has context."""
        self.messages.append({"role": "user", "content": user_text})

        if self.cfg.kind == "claude_cli":
            # Real `claude` CLI — full tools, autonomy, your loaded context.
            full: list[str] = []
            yield from self._stream_claude_cli(user_text, full)
            self.messages.append({"role": "assistant", "content": "".join(full)})

        elif self.cfg.kind in ("anthropic_oauth", "anthropic_key"):
            # Direct Anthropic API (the token path — kept as an option).
            full = []
            with self.cfg.client.messages.stream(
                model=self.cfg.model,
                max_tokens=_MAX_TOKENS,
                system=self._system_prompt(),
                messages=self.messages,
            ) as stream:
                for chunk in stream.text_stream:
                    full.append(chunk)
                    yield ("text", chunk)
            self.messages.append({"role": "assistant", "content": "".join(full)})

        else:
            # OpenAI-compatible (Kimi / OpenRouter) — now an agent WITH tools.
            # This branch records its own turns (tool calls + results + answer)
            # into self.messages, so it doesn't fall through to a shared append.
            yield from self._stream_openai_tools()

    def _stream_openai_tools(self):
        """Run the Kimi/OpenRouter brain as a tool-using agent.

        Loops: ask the model → if it calls tools, run them, feed the results back,
        and ask again → repeat until it answers with no more tool calls. Yields
        (kind, text) pairs ("thinking"/"tool"/"tool_result"/"text") so the terminal
        and gateway render the work live — exactly like the claude path.
        """
        from . import tools  # local import: only the openai path needs the tool belt

        system = {"role": "system", "content": self._system_prompt()}

        for _ in range(_MAX_TOOL_STEPS):
            resp = self.cfg.client.chat.completions.create(
                model=self.cfg.model,
                max_tokens=_MAX_TOKENS,
                messages=[system, *self.messages],
                tools=tools.SCHEMAS,
                tool_choice="auto",
            )
            msg = resp.choices[0].message
            tool_calls = list(msg.tool_calls or [])

            if not tool_calls:
                # Final answer — no more actions needed.
                text = msg.content or ""
                self.messages.append({"role": "assistant", "content": text})
                if text:
                    yield ("text", text)
                return

            # The model wants to act. Surface any narration / reasoning it gave.
            narration = msg.content or getattr(msg, "reasoning_content", "") or ""
            if narration.strip():
                yield ("thinking", narration.strip())

            # Record the assistant's tool-call turn in the exact shape the API
            # needs echoed back next round (id + name + raw JSON args).
            self.messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name,
                                  "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ],
            })

            # Run each tool, stream the action + a slice of its result, and feed
            # the full result back as a 'tool' message keyed to its call id. If a
            # tool produced a screenshot, stash it to show the model as an image.
            for tc in tool_calls:
                name = tc.function.name
                args = tc.function.arguments
                yield ("tool", tools.short_detail(name, args))
                result = tools.dispatch(name, args)
                clean, image_path = tools.pop_image_path(result)
                yield ("tool_result", clean.strip()[:200])
                self.messages.append({
                    "role": "tool", "tool_call_id": tc.id, "content": clean,
                })
                if image_path and self._vision:
                    self._pending_images.append(image_path)

            # Show the model the screenshots it just took (it's vision-capable),
            # so the next round it reasons over what it actually SEES.
            self._flush_pending_images()

        # Ran out of steps — tell the operator rather than hanging silently.
        msg = "(stopped after hitting the tool-step limit — say 'continue' to keep going.)"
        self.messages.append({"role": "assistant", "content": msg})
        yield ("text", msg)

    def _flush_pending_images(self) -> None:
        """Append captured screenshots as a vision user-message so the model SEES
        them next round. Base64-inlines each PNG; skips any it can't read."""
        if not self._pending_images:
            return
        content = [{"type": "text",
                    "text": "Screenshots you just captured — view them to verify your work:"}]
        for path in self._pending_images:
            try:
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                })
            except Exception:
                continue  # unreadable shot — skip, don't break the turn
        if len(content) > 1:
            self.messages.append({"role": "user", "content": content})
        self._pending_images = []

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
