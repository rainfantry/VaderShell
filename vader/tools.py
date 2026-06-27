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
import re
import shutil
import subprocess
import urllib.request

# Home, where the user's real env/auth lives.
_HOME = os.path.expanduser("~")

# VADER's workspace: where it clones / creates / builds repos so it doesn't junk
# up home. Override with VADER_WORKSPACE. Commands run here; relative file paths
# resolve here. Created on import.
WORKSPACE = (os.environ.get("VADER_WORKSPACE", "").strip()
             or os.path.join(_HOME, "vader-workspace"))
_SHOTS = os.path.join(WORKSPACE, ".shots")  # screenshots land here
for _d in (WORKSPACE, _SHOTS):
    try:
        os.makedirs(_d, exist_ok=True)
    except Exception:
        pass

# Hard caps so a chatty command can't blow the model's context window.
_MAX_OUT = 12000         # chars of a tool result fed back to the model
_DEFAULT_TIMEOUT = 300   # seconds before a command is killed (builds are slow)


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
            argv, cwd=WORKSPACE, capture_output=True, text=True,
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
    """Expand ~ and make relative paths resolve from the workspace (the work dir)."""
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(WORKSPACE, path)
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


# ── Tool: screenshots (so VADER can SEE its work, like a human dev) ────────
# Both save a PNG and return a "[[IMG:<path>]]" marker. core.py spots the marker
# and feeds the image back into the conversation so the (vision-capable) model
# actually views it — the same loop a person uses: build → screenshot → look → fix.

def _find_browser() -> str:
    """Locate Edge or Chrome for headless screenshots (no extra deps needed)."""
    for name in ("msedge", "chrome", "chromium"):
        p = shutil.which(name)
        if p:
            return p
    for p in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ):
        if os.path.exists(p):
            return p
    return ""


def screenshot_desktop(path: str = "") -> str:
    """Capture the whole desktop to a PNG (Windows .NET via PowerShell — no deps)."""
    out = _resolve(path or os.path.join(_SHOTS, "desktop.png"))
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
    except Exception:
        pass
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
        "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
        "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
        "$g=[System.Drawing.Graphics]::FromImage($bmp);"
        "$g.CopyFromScreen($b.X,$b.Y,0,0,$bmp.Size);"
        f"$bmp.Save('{out}');$g.Dispose();$bmp.Dispose()"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=60)
    except Exception as e:  # noqa: BLE001
        return f"ERROR: desktop screenshot failed: {e}"
    if not os.path.exists(out):
        return f"ERROR: desktop screenshot failed: {(r.stderr or '').strip()[:200]}"
    return f"[[IMG:{out}]] desktop screenshot saved to {out}"


def screenshot_url(url: str, path: str = "", width: int = 1366, height: int = 900) -> str:
    """Render a web page headless (Edge/Chrome) and save a PNG. Use to SEE a web
    app you're building after starting its dev server with run_terminal."""
    if not url or not url.strip():
        return "ERROR: empty url."
    browser = _find_browser()
    if not browser:
        return "ERROR: no Edge/Chrome found for headless screenshot."
    out = _resolve(path or os.path.join(_SHOTS, "page.png"))
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        width, height = int(width), int(height)
    except Exception:
        width, height = 1366, 900
    argv = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--no-sandbox", f"--window-size={width},{height}",
            f"--screenshot={out}", url]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=90)
    except Exception as e:  # noqa: BLE001
        return f"ERROR: page screenshot failed: {e}"
    if not os.path.exists(out):
        return f"ERROR: page screenshot failed: {(r.stderr or '').strip()[:200]}"
    return f"[[IMG:{out}]] screenshot of {url} saved to {out}"


# Marker the screenshot tools embed; core.py extracts the path to feed the image
# back to the model, then shows the model a cleaned result string.
_IMG_RE = re.compile(r"\[\[IMG:(.+?)\]\]\s*")


def pop_image_path(result: str):
    """Split a tool result into (clean_text, image_path_or_None)."""
    m = _IMG_RE.search(result or "")
    if not m:
        return result, None
    return _IMG_RE.sub("", result, count=1).strip(), m.group(1)


# ── Persistent memory & skills (learning that survives restart) ────────────
# Stored under ~/.vader (override with VADER_HOME) — OUTSIDE the repo, so it's
# personal and durable. core.py folds memory + the skills index into the system
# prompt every turn, so anything saved here is in effect on the very next message
# AND after a restart (it's just files on disk).
VADER_HOME = (os.environ.get("VADER_HOME", "").strip()
              or os.path.join(_HOME, ".vader"))
_MEMORY_FILE = os.path.join(VADER_HOME, "MEMORY.md")
_SKILLS_DIR = os.path.join(VADER_HOME, "skills")
for _d in (VADER_HOME, _SKILLS_DIR):
    try:
        os.makedirs(_d, exist_ok=True)
    except Exception:
        pass


def _skill_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return slug or "skill"


def remember(fact: str) -> str:
    """Append a durable fact / preference to long-term memory."""
    fact = (fact or "").strip()
    if not fact:
        return "ERROR: empty fact."
    try:
        with open(_MEMORY_FILE, "a", encoding="utf-8") as f:
            f.write(f"- {fact}\n")
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"
    return f"remembered: {fact}"


def recall() -> str:
    """Read everything in long-term memory."""
    if not os.path.exists(_MEMORY_FILE):
        return "(memory empty)"
    try:
        with open(_MEMORY_FILE, "r", encoding="utf-8", errors="replace") as f:
            return _clip(f.read().strip()) or "(memory empty)"
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"


def save_skill(name: str, description: str, steps: str) -> str:
    """Save a reusable workflow as a skill that persists across restarts."""
    if not (steps or "").strip():
        return "ERROR: empty steps."
    slug = _skill_slug(name)
    path = os.path.join(_SKILLS_DIR, slug + ".md")
    body = (f"---\ndescription: {(description or '').strip()}\n---\n"
            f"# {name}\n\n{steps.strip()}\n")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"
    return f"saved skill '{slug}' — available now and after restart ({path})."


def _skill_files():
    try:
        return sorted(p for p in os.listdir(_SKILLS_DIR) if p.endswith(".md"))
    except Exception:
        return []


def list_skills() -> str:
    """List saved skills and their one-line descriptions."""
    files = _skill_files()
    if not files:
        return "(no skills saved yet)"
    out = []
    for fn in files:
        desc = ""
        try:
            with open(os.path.join(_SKILLS_DIR, fn), "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip()
                        break
        except Exception:
            pass
        out.append(f"- {fn[:-3]}: {desc}" if desc else f"- {fn[:-3]}")
    return "\n".join(out)


def use_skill(name: str) -> str:
    """Load a saved skill's full steps so you can follow them."""
    slug = _skill_slug(name)
    path = os.path.join(_SKILLS_DIR, slug + ".md")
    if not os.path.exists(path):
        return f"ERROR: no skill '{slug}'. Available:\n{list_skills()}"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return _clip(f.read())
    except Exception as e:  # noqa: BLE001
        return f"ERROR: {e}"


# Helpers core.py uses to fold memory + skills into the system prompt each turn.
def memory_text() -> str:
    if not os.path.exists(_MEMORY_FILE):
        return ""
    try:
        with open(_MEMORY_FILE, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except Exception:
        return ""


def skills_index() -> str:
    return list_skills() if _skill_files() else ""


# ── Registry ──────────────────────────────────────────────────────────────
# name → callable
_HANDLERS = {
    "run_terminal": run_terminal,
    "web_search": web_search,
    "fetch_url": fetch_url,
    "read_file": read_file,
    "write_file": write_file,
    "list_dir": list_dir,
    "screenshot_desktop": screenshot_desktop,
    "screenshot_url": screenshot_url,
    "remember": remember,
    "recall": recall,
    "save_skill": save_skill,
    "use_skill": use_skill,
    "list_skills": list_skills,
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
            "description": "List a directory's entries (files and folders). Default is the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot_desktop",
            "description": ("Capture the whole desktop to a PNG and SEE it. Use to check a running "
                            "GUI app, an editor, or anything on screen."),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Optional output path."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "screenshot_url",
            "description": ("Render a web page headless (Edge/Chrome) to a PNG and SEE it. The key "
                            "web-dev check: after starting a dev server with run_terminal, screenshot "
                            "e.g. http://localhost:3000 to verify the UI rendered, then fix and repeat."),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "path": {"type": "string", "description": "Optional output path."},
                    "width": {"type": "integer", "description": "Viewport width (default 1366)."},
                    "height": {"type": "integer", "description": "Viewport height (default 900)."},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": ("Save a durable fact or preference to long-term memory (persists across "
                            "restarts). Use whenever George tells you something to remember, or you "
                            "learn a lasting preference (e.g. 'George deploys to Vercel')."),
            "parameters": {
                "type": "object",
                "properties": {"fact": {"type": "string"}},
                "required": ["fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "Read everything in your long-term memory.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_skill",
            "description": ("Save a reusable workflow as a named skill that persists across restarts. "
                            "Use when you've worked out a repeatable procedure worth keeping. Write "
                            "'steps' as clear, numbered instructions you (or future-you) can follow."),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short skill name, e.g. 'scaffold-react-app'."},
                    "description": {"type": "string", "description": "One line: what it does / when to use it."},
                    "steps": {"type": "string", "description": "The full step-by-step workflow."},
                },
                "required": ["name", "description", "steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "use_skill",
            "description": ("Load a saved skill's full steps so you can follow them. Call this BEFORE "
                            "doing a task you have a matching skill for."),
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_skills",
            "description": "List the skills you've saved and their descriptions.",
            "parameters": {"type": "object", "properties": {}},
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
              or arguments.get("url") or arguments.get("path")
              or arguments.get("name") or arguments.get("fact") or "")
    return f"{name} {detail}".strip()
