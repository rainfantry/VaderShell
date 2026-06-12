# VaderShell — terminal agent launcher. Works from any clone location.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = $root
& "$root\.venv\Scripts\python.exe" -m vader.terminal
