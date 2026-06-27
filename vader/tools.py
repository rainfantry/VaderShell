"""
22DIV — VADER's hands. The tool belt for the kimi/openrouter (OpenAI-compatible)
brains so they can ACT, not just talk.

The claude-CLI brain already has full tools (it IS Claude Code). This module gives
the *other* brains the same reach: run terminal commands (which is all `gh`, `git`,
clone/push, build, npm, python, etc. really are), search the web, and read/write
files.

Two halves:
  - SCHEMAS  : OpenAI "tools" definitions the model sees and chooses from.
  - dispatch : runs the chosen tool by name and returns a string result.

Everything runs in George's home directory and inherits his real environment —
his logged-in `gh`/`git` auth, his PATH, his keys. The Discord gateway is locked
to his user id, so only he can drive this. Full autonomy by design (same posture
as the claude path's --dangerously-skip-permissions).
"""

import json
import os
import subprocess
import urllib.request

# Where commands run + files resolve from. Home, so `gh`/`git`/CLAUDE.md/skills
# all behave exactly like they do in George's own terminal.
_HOME = os.path.expanduser("~")

# Hard caps so a chatty command can't blow the model's context window.
_MAX_OUT = 6000          # chars of a tool result fed back to the model
_DEFAULT_TIMEOUT = 120   # seconds before a command is killed


def _clip(text: str, limit: int = _MAX_OUT) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[truncated, {len(text) - limit} more chars]"


# ── Tool: run_terminal ────────────────────────────────────────────────────
def run_terminal(command: str, shell: str = "powershell", timeout: int = _DEFAULT_TIMEOUT) -> str:
    """Run a shell command on the box and return exit code + stdout + stderr.

    This is the workhorse: `gh auth status`, `git clone <private repo>`,
    `git push`, `npm run build`, `python x.py` — all of it is just this.
    """
    if not command or not command.strip():
        return "ERROR: empty command."
    shell = (shell or "powershell").lower()
    try:
        timeout = int(timeout) or _DEFAULT_TIMEOUT
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT

    if shell == "bash":
        argv = ["bash", "-lc", command]
    elif shell == "cmd":
        argv = ["cmd", "/c", command]
    else:  # powershell (default)
        argv = ["powershell", "-NoProfile", "-Command", command]

    try:
        proc = subprocess.run(
            argv, cwd=_HOME, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except FileNotFoundError:
        return f"ERROR: shell '{shell}' not found on PATH."
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout}s."
    except Exception as e:  # noqa: BLE001 — surface anything, don't crash the loop
        return f"ERROR: {e}"

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    parts = [f"exit code: {proc.returncode}"]
    if out:
        parts.append("stdout:\n" + out)
    if err:
        parts.append("stderr:\n" + err)
    if not out and not err:
        parts.append("(no output)")
    return _clip("\n".join(parts))


# ── Tool: web_search ──────────────────────────────────────────────────────
def web_search(query: str, max_results: int = 5) -> str:
    """Search the web (DuckDuckGo, no API key) → titles, URLs, snippets."""
    if not query or not query.strip():
        return "ERROR: empty query."
    try:
        max_results = max(1, min(int(max_results), 10))
    except (TypeError, ValueError):
        max_results = 5
    try:
        from ddgs import DDGS  # maintained fork of duckduckgo_search
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # older name, fallback
        except ImportError:
            return ("ERROR: web search needs the 'ddgs' package. Install it with: "
                    "run_terminal  pip install ddgs")
    try:
        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=max_results))
    except Exception as e:  # noqa: BLE001
        return f"ERROR: search failed: {e}"
    if not hits:
        return "(no results)"
    lines = []
    for i, h in enumerate(hits, 1):
        title = h.get("title", "")
        href = h.get("href") or h.get("url", "")
        body = h.get("body", "")
        lines.append(f"{i}. {title}\n   {href}\n   {body}")
    return _clip("\n".join(lines))


# ── Tool: fetch_url ───────────────────────────────────────────────────────
def fetch_url(url: str, max_chars: int = 4000) -> str:
    """Fetch a URL and return its text (HTML tags stripped, roughly)."""
    if not url or not url.strip():
        return "ERROR: empty url."
    try:
        max_chars = max(200, min(int(max_chars), _MAX_OUT))
    except (TypeError, ValueError):
        max_chars = 4000
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (VaderShell)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read(2_000_000).decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        return f"ERROR: fetch failed: {e}"
    import re
    # Drop scripts/styles, strip tags, collapse whitespace — a cheap readability pass.
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text).strip()
    return _clip(text, max_chars)


# ── Tool: read_file / write_file / list_dir ───────────────────────────────
def _resolve(path: str) -> str:
    """Expand ~ and make relative paths resolve from home (the work dir)."""
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(_HOME, path)
    return path


def read_file(path: str, max_chars: int = _MAX_OUT) -> str:
    p = _resolve(path)
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return _clip(f.read(), int(max_chars) if max_chars else _MAX_OUT)
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"


def write_file(path: str, content: str) -> str:
    p = _resolve(path)
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content or "")
        return f"wrote {len(content or '')} chars to {p}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"


def list_dir(path: str = ".") -> str:
    p = _resolve(path)
    try:
        entries = sorted(os.listdir(p))
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"
    if not entries:
        return "(empty)"
    out = []
    for name in entries:
        full = os.path.join(p, name)
        out.append(f"{'DIR ' if os.path.isdir(full) else 'FILE'}  {name}")
    return _clip("\n".join(out))


# ── Registry ──────────────────────────────────────────────────────────────
# name → callable
_HANDLERS = {
    "run_terminal": run_terminal,
    "web_search": web_search,
    "fetch_url": fetch_url,
    "read_file": read_file,
    "write_file": write_file,
    "list_dir": list_dir,
}

# OpenAI "tools" schema the model is shown. Keep descriptions sharp — the model
# picks tools off these alone.
SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_terminal",
            "description": (
                "Run a shell command on George's Windows machine and get its exit code, "
                "stdout and stderr. This is how you do EVERYTHING actionable: gh CLI "
                "(`gh auth status`, `gh repo clone`, `gh pr ...`), git (clone/commit/push, "
                "including private repos via the logged-in gh/git auth), build/test "
                "(`npm run build`, `python x.py`, `dotnet build`), file ops, installs. "
                "Runs in the home directory. Prefer shell='cmd' for python/node scripts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The command line to run."},
                    "shell": {"type": "string", "enum": ["powershell", "cmd", "bash"],
                              "description": "Which shell. Default powershell; use cmd for python/node, bash for POSIX."},
                    "timeout": {"type": "integer", "description": "Seconds before kill (default 120)."},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web and get titles, URLs and snippets. Use for current info, docs, errors.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "description": "1-10, default 5."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch a web page and return its readable text. Use after web_search to read a result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_chars": {"type": "integer", "description": "Cap returned text (default 4000)."},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file. Relative paths resolve from the home directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_chars": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write (overwrite) a text file, creating parent folders. Use for code/config you generate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List a directory's entries (files and folders). Default is the home directory.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    },
]


def dispatch(name: str, arguments) -> str:
    """Run tool `name` with `arguments` (dict or JSON string) → result string."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"ERROR: unknown tool '{name}'."
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return f"ERROR: tool '{name}' got non-JSON arguments."
    if not isinstance(arguments, dict):
        arguments = {}
    try:
        return handler(**arguments)
    except TypeError as e:
        return f"ERROR: bad arguments for '{name}': {e}"
    except Exception as e:  # noqa: BLE001
        return f"ERROR: tool '{name}' crashed: {e}"


def short_detail(name: str, arguments) -> str:
    """A one-line label for the (kind='tool') stream event, e.g. 'run_terminal git push'."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}
    detail = (arguments.get("command") or arguments.get("query")
              or arguments.get("url") or arguments.get("path") or "")
    return f"{name} {detail}".strip()
