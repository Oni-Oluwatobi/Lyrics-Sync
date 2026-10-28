# Build Lyric Sync as a Windows desktop app.
#
#   powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1
#   powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1 -SkipTests
#
# Result: dist\LyricSync\LyricSync.exe  (folder build)

param(
    [switch]$SkipTests,
    [switch]$Fixture
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Invoke-Step {
    param([string]$Label, [string]$File, [string[]]$Args)
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $File @Args
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed ($Label), exit code $LASTEXITCODE"
    }
}

Invoke-Step "Install dependencies" "python" @("-m", "pip", "install", "-r", "requirements.txt", "pyinstaller")

if (-not $SkipTests) {
    Invoke-Step "Run test suite" "python" @("-m", "pytest", "tests", "-q")
}

if ($Fixture) {
    Invoke-Step "Build development fixture" "python" @("tools\build_dev_fixture.py")
}

Invoke-Step "Package (PyInstaller)" "python" @("-m", "PyInstaller", "--clean", "--noconfirm", "lyricsync.spec")

$exe = Join-Path $root "dist\LyricSync\LyricSync.exe"
if (-not (Test-Path $exe)) {
    throw "Build finished but $exe was not found"
}

Write-Host ""
Write-Host "Build complete: $exe" -ForegroundColor Green
Write-Host "Place the Gospel database at:  dist\LyricSync\data\lyric_sync_gospel.lsdb"
Write-Host "(or run LyricSync.exe with LYRIC_SYNC_DATABASE=C:\path\to\songbook.lsdb)"
