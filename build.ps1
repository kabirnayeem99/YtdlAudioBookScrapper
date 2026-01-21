Param(
    [string]$Target = "$Env:LOCALAPPDATA\Microsoft\WindowsApps\ytdl-audiobook.py"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$source = Join-Path $scriptDir "ytdl_audiobook_scraper.py"
if (-not (Test-Path $source)) {
    throw "Source script not found at $source"
}

$destinationDir = Split-Path -Parent $Target
if (-not (Test-Path $destinationDir)) {
    New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
}

Copy-Item -Path $source -Destination $Target -Force

Write-Host "Installed ytdl audiobook CLI to $Target"
Write-Host "Reminder: ensure 'yt-dlp' and 'ffmpeg' live in PATH (scoop/choco installers work great)."
