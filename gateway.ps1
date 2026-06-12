# VaderShell — Discord gateway launcher. Stays running and listens; Ctrl-C to stop.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = $root
& "$root\.venv\Scripts\python.exe" -m vader.gateway_discord
