"""VaderShell — quick smoke test: resolve the provider and stream one turn."""
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")
sys.path.insert(0, str(_ROOT))

from vader.auth import resolve
from vader.core import Agent

cfg = resolve()
print("[resolved]", cfg.provider, cfg.model, cfg.kind)
agent = Agent(cfg)
for kind, text in agent.stream_reply("Reply with exactly: VADER online."):
    print("<" + kind + "> " + text[:120].replace(chr(10), " "))
print("[done]")
