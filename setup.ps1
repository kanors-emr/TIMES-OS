# Machine setup for TIMES (this repository).
# What this does, in order:
#   1. Checks Python 3.11+ (does not install it); notes whether git is there (optional).
#   2. Notes whether Julia is on the PATH; if not, the setup below installs it (winget's Juliaup, the Microsoft
#      Store's Julia, or a portable copy from julialang.org into .julia_bin).
#   3. Runs: python TIMES.py setup
#      That creates .venv, installs the Python packages there, installs the Julia packages
#      (TimesEq, JuMP, HiGHS), and solves models\DemoS_012.  Later commands use .venv on their own.
#
# From this folder:
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Write-Step([string]$text) {
    Write-Host ""
    Write-Host $text
}

function Refresh-Path {
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $env:Path = "$user;$machine"
}

Write-Step "1. Python 3.11 or newer"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Python was not found. Install it, open a new terminal, and run this script again: winget install Python.Python.3.12"
}
& python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python is older than 3.11 ($($python.Source)). Install a newer one: winget install Python.Python.3.12"
}
$pyver = (& python -c "import sys; print(sys.version.split()[0])").Trim()
Write-Host "   $pyver ($($python.Source))"

Write-Step "2. git (optional)"
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
    Write-Host "   $((& git --version).Trim())"
} else {
    Write-Host "   not found: fine for a downloaded copy (git only names the code's revision in the reports)"
}

Write-Step "3. Julia"
$julia = Get-Command julia -ErrorAction SilentlyContinue
if ($julia) {
    Write-Host "   $($julia.Source)"
} else {
    Write-Host "   not found: the next step installs it (winget's Juliaup, the Microsoft Store's Julia, or a portable copy)"
}

Write-Step "4. python TIMES.py setup"
& python (Join-Path $PSScriptRoot "TIMES.py") setup
exit $LASTEXITCODE
