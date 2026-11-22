param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
$environmentPython = Join-Path $projectRoot ".venv/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $environmentPython)) {
    & $Python -c "import sys; assert (3,12) <= sys.version_info[:2] < (3,14), 'Use Python 3.12 or 3.13 with these pinned packages; 3.13.5 is verified'"
    if ($LASTEXITCODE -ne 0) { throw "Python version check failed" }
    & $Python -m venv (Join-Path $projectRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }
}
& $environmentPython -c "import sys; assert (3,12) <= sys.version_info[:2] < (3,14), 'Existing venv needs Python 3.12 or 3.13; 3.13.5 is verified'"
if ($LASTEXITCODE -ne 0) { throw "Existing environment version check failed" }
& $environmentPython -m pip install --disable-pip-version-check --no-cache-dir -r (Join-Path $projectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed" }
& $environmentPython -m pip check
if ($LASTEXITCODE -ne 0) { throw "Dependency check failed" }
Write-Output "Environment ready: $environmentPython"
