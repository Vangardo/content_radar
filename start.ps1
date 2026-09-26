$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Environment missing. Run setup.ps1 first (see README_LOCAL.md).'
}
& $taskPython -X utf8 -m app
exit $LASTEXITCODE
