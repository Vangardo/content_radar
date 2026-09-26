$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'Install uv or create a Python 3.11+ environment with SQLite 3.51.3+. See README_LOCAL.md.'
}
uv venv --python 3.11.15 .venv
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv pip sync --python .venv/Scripts/python.exe requirements-local.lock
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& .venv/Scripts/python.exe -X utf8 -c "import sqlite3; from zoneinfo import ZoneInfo; print('SQLite:', sqlite3.sqlite_version); print(ZoneInfo('America/Los_Angeles'))"
