# VaderShell — Discord gateway launcher. Stays running and listens; Ctrl-C to stop.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = $root
# Gateway (phone) runs on Sonnet — lighter, and on most plans a separate quota.
# The terminal stays on Opus (its default) for heavier work at the machine.
$env:VADER_CLAUDE_MODEL = "claude-sonnet-4-6"
& "$root\.venv\Scripts\python.exe" -m vader.gateway_discord
