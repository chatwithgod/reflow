param([string]$GoExe = 'go', [string]$Compiler = '', [string]$CodexExe = '', [string]$PiCli = '', [string]$NodeExe = '', [string]$ProxyExe = '', [string]$PluginMarketplace = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$reportDir = Join-Path $projectRoot "build/verification/$stamp"
New-Item -ItemType Directory -Path $reportDir -ErrorAction Stop | Out-Null
$env:GOPATH = Join-Path $projectRoot '.tools/gopath'
$env:GOCACHE = Join-Path $projectRoot '.tools/gocache'
$env:GOTOOLCHAIN = 'local'
if ($Compiler) { $env:CC = $Compiler }
if ($CodexExe) { $env:REFLOW_CODEX_BIN = $CodexExe } else { Remove-Item Env:REFLOW_CODEX_BIN -ErrorAction SilentlyContinue }
if ($PiCli) { $env:REFLOW_PI_CLI = $PiCli } else { Remove-Item Env:REFLOW_PI_CLI -ErrorAction SilentlyContinue }
if ($NodeExe) { $env:REFLOW_NODE_BIN = $NodeExe } else { Remove-Item Env:REFLOW_NODE_BIN -ErrorAction SilentlyContinue }
if ($ProxyExe) { $env:REFLOW_PROXY_BIN = $ProxyExe } else { Remove-Item Env:REFLOW_PROXY_BIN -ErrorAction SilentlyContinue }
if ($PluginMarketplace) { $env:REFLOW_PLUGIN_MARKETPLACE = $PluginMarketplace } else { Remove-Item Env:REFLOW_PLUGIN_MARKETPLACE -ErrorAction SilentlyContinue }
$env:CGO_ENABLED = '1'
& $GoExe test -count=1 -json ./... 2>&1 | Tee-Object -FilePath (Join-Path $reportDir 'tests.jsonl')
if ($LASTEXITCODE -ne 0) { throw 'Tests failed; evidence preserved.' }
& $GoExe test -race -count=1 -json ./... 2>&1 | Tee-Object -FilePath (Join-Path $reportDir 'race.jsonl')
if ($LASTEXITCODE -ne 0) { throw 'Race tests failed; evidence preserved.' }
& $GoExe vet ./... 2>&1 | Tee-Object -FilePath (Join-Path $reportDir 'vet.txt')
if ($LASTEXITCODE -ne 0) { throw 'Vet failed; evidence preserved.' }
& $GoExe test ./core -run '^$' -fuzz FuzzDecoderChunkBoundaries -fuzztime=5s -parallel=2 2>&1 | Tee-Object -FilePath (Join-Path $reportDir 'fuzz.txt')
if ($LASTEXITCODE -ne 0) { throw 'Decoder fuzzing failed; evidence preserved.' }
$events = Get-Content -LiteralPath (Join-Path $reportDir 'tests.jsonl') | ForEach-Object { try { $_ | ConvertFrom-Json } catch { } }
$summary = [ordered]@{
    created_utc = [DateTime]::UtcNow.ToString('o')
    go_version = (& $GoExe version)
    tests_passed = @($events | Where-Object { $_.Action -eq 'pass' -and $_.Test }).Count
    tests_skipped = @($events | Where-Object { $_.Action -eq 'skip' -and $_.Test }).Count
    race = 'pass'; vet = 'pass'; decoder_fuzz = 'pass'
    native_cli_synthetic_auth = [bool]$CodexExe
    native_workspace_write_probe = 'excluded: run native_write_probe tag separately; see docs/NATIVE-WRITE-PROBE.md'
    native_cli_version = $(if ($CodexExe) { & $CodexExe --version } else { $null })
    pi_cli_synthetic_oauth = [bool]$PiCli
    pi_cli_version = $(if ($PiCli) { $piRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PiCli)); (Get-Content -LiteralPath (Join-Path $piRoot 'package.json') -Raw | ConvertFrom-Json).version } else { $null })
    proxy_binary_sha256 = $(if ($ProxyExe) { (Get-FileHash -LiteralPath $ProxyExe -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null })
    native_plugin_synthetic_auth = [bool]($CodexExe -and $PluginMarketplace)
    plugin_marketplace = $PluginMarketplace
    live_account = $false; live_model = $false
    desktop_and_dot = 'not tested'; production_modified = $false
}
$summary | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $reportDir 'summary.json') -Encoding utf8
Write-Output "Verification saved: $reportDir"
