$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:UV_CACHE_DIR = Join-Path $projectRoot '.cache\uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.cache\python'
$env:electron_config_cache = Join-Path $projectRoot '.cache\electron'
$env:npm_config_cache = Join-Path $projectRoot '.cache\npm'
foreach ($tool in @('node', 'npm.cmd', 'uv')) {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "Missing tool: $tool. See README.md." }
}
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
$pythonSpec = if ($env:QIBAN_PYTHON) { $env:QIBAN_PYTHON } else { '3.12' }
uv sync --frozen --extra dev --extra voice --python $pythonSpec
if ($LASTEXITCODE -ne 0) { throw 'Python dependency setup failed.' }
npm.cmd ci
if ($LASTEXITCODE -ne 0) { throw 'Node dependency setup failed.' }
npm.cmd run assets
if ($LASTEXITCODE -ne 0) { throw 'Asset setup failed.' }
npm.cmd run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
Write-Output 'Setup complete. Fill CHAT_API_KEY in .env, then run the desktop launcher.'
