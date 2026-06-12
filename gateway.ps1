# VaderShell — Discord gateway launcher + supervisor.
#
# Loops so the gateway can reboot itself:
#   /restart in Discord -> gateway exits 42 -> relaunch (reconnects in a few seconds)
#   a crash (other exit) -> auto-relaunch, up to 5 times, with a short backoff
#   a clean exit (0)      -> stop
# So you can reboot the bot from your phone, even away from the machine.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = $root
# Gateway runs on Sonnet (lighter; a separate quota on most plans).
$env:VADER_CLAUDE_MODEL = "claude-sonnet-4-6"

$crashes = 0
while ($true) {
    & "$root\.venv\Scripts\python.exe" -m vader.gateway_discord
    $code = $LASTEXITCODE
    if ($code -eq 42) { Write-Host "[supervisor] /restart -> relaunching..."; $crashes = 0; continue }
    if ($code -eq 0)  { Write-Host "[supervisor] clean exit -> stopping."; break }
    $crashes++
    if ($crashes -ge 5) { Write-Host "[supervisor] too many crashes ($crashes) -> stopping."; break }
    Write-Host "[supervisor] gateway exited ($code) -> relaunching in 3s (crash $crashes/5)..."
    Start-Sleep -Seconds 3
}
