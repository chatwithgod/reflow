param(
    [string]$Version = '',
    [string]$Repository = ''
)
$ErrorActionPreference = 'Stop'
if (-not $Version) { $Version = (Get-Content -LiteralPath (Join-Path $PSScriptRoot '../VERSION') -Raw).Trim() }
if ($Version -notmatch '^\d+\.\d+\.\d+(-dev(\.\d+)?)?$') { throw 'Invalid version.' }
if ($Repository -and $Repository -notmatch '^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw 'Repository must be an exact GitHub repository URL.'
}
. (Join-Path $PSScriptRoot 'dev_env.ps1')
Push-Location $ProjectRoot
try {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $output = Join-Path $ProjectRoot "build/development/$Version/$stamp"
    if (Test-Path -LiteralPath $output) { throw 'Build output already exists; refusing to overwrite.' }
    New-Item -ItemType Directory -Path $output | Out-Null
    $library = Join-Path $output 'codexreflow.dll'
    $Flags = "-X main.pluginVersion=$Version"
    if ($Repository) { $Flags += " -X main.pluginRepository=$Repository" }
    & go build -trimpath -buildmode=c-shared -ldflags $Flags -o $library .
    if ($LASTEXITCODE -ne 0) { throw 'DLL build failed.' }
    Get-FileHash -LiteralPath $library -Algorithm SHA256
} finally {
    Pop-Location
}
