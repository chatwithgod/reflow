param(
    [string]$Version = '0.1.0-dev.5',
    [string]$Repository = ''
)
$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^\d+\.\d+\.\d+(-dev(\.\d+)?)?$') { throw 'Invalid version.' }
if ($Repository -and $Repository -notmatch '^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw 'Repository must be an exact GitHub repository URL.'
}
. (Join-Path $PSScriptRoot 'dev_env.ps1')
Push-Location $ProjectRoot
try {
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot 'build') | Out-Null
    $Flags = "-X main.pluginVersion=$Version"
    if ($Repository) { $Flags += " -X main.pluginRepository=$Repository" }
    & go build -trimpath -buildmode=c-shared -ldflags $Flags -o build/codexreflow.dll .
    if ($LASTEXITCODE -ne 0) { throw 'DLL build failed.' }
    Get-FileHash -LiteralPath build/codexreflow.dll -Algorithm SHA256
} finally {
    Pop-Location
}
