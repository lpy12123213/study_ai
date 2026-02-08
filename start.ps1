param(
  [Parameter(Position = 0)]
  [string]$Command = 'dev'
)

$ErrorActionPreference = 'Stop'

function Show-Usage {
  Write-Host @"
Usage:
  start.bat                 (dev: backend + frontend)
  start.bat dev             (backend + frontend)
  start.bat all             (backend + frontend + mcp)
  start.bat backend         (backend only)
  start.bat frontend        (frontend only)
  start.bat mcp             (mcp only)
  start.bat setup           (install deps only)
  start.bat doctor          (run smoke checks)

Notes:
  - Press Ctrl+C once to stop everything.
  - Frontend dev server auto-picks a free port (3000/3001/...) and opens browser.
"@
}

function Resolve-SystemPython {
  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCmd) {
    return @('python')
  }
  $pyCmd = Get-Command py -ErrorAction SilentlyContinue
  if ($pyCmd) {
    return @('py', '-3')
  }
  throw "Python not found in PATH. Please install Python 3.8+ and retry."
}

function Ensure-Venv {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Root
  )
  $venvPython = Join-Path $Root 'venv\Scripts\python.exe'
  if (Test-Path $venvPython) {
    return $venvPython
  }

  $sysPython = Resolve-SystemPython
  Write-Host "[setup] Creating virtual environment..." -ForegroundColor Cyan
  & $sysPython -m venv (Join-Path $Root 'venv')
  if (-not (Test-Path $venvPython)) {
    throw "Failed to create venv: $venvPython not found"
  }
  return $venvPython
}

function Ensure-BackendDeps {
  param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,
    [Parameter(Mandatory = $true)]
    [string]$Root
  )

  Write-Host "[setup] Checking backend deps..." -ForegroundColor Cyan

  # NOTE: some tools (pip / playwright installer) print warnings to stderr even
  # on success. With `$ErrorActionPreference = 'Stop'` that can terminate the
  # script. Temporarily suppress native stderr error records, and rely on
  # `$LASTEXITCODE` for the real success/failure signal.
  $oldEap = $ErrorActionPreference
  $ErrorActionPreference = 'SilentlyContinue'
  & $PythonExe -m pip show fastapi *> $null
  $pipShowExit = $LASTEXITCODE
  $ErrorActionPreference = $oldEap

  if ($pipShowExit -ne 0) {
    & $PythonExe -m pip install -r (Join-Path $Root 'requirements.txt')
  }

  $oldEap = $ErrorActionPreference
  $ErrorActionPreference = 'SilentlyContinue'
  & $PythonExe -m playwright --version *> $null
  $playwrightVersionExit = $LASTEXITCODE
  $ErrorActionPreference = $oldEap

  if ($playwrightVersionExit -ne 0) {
    & $PythonExe -m pip install playwright
  }

  $oldEap = $ErrorActionPreference
  $ErrorActionPreference = 'SilentlyContinue'
  & $PythonExe -m playwright install chromium *> $null
  $playwrightInstallExit = $LASTEXITCODE
  $ErrorActionPreference = $oldEap

  if ($playwrightInstallExit -ne 0) {
    throw "[setup] Failed to install Playwright Chromium (exit code $playwrightInstallExit). Try: `"$PythonExe`" -m playwright install chromium"
  }
}

function Ensure-FrontendDeps {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Root
  )

  $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
  if (-not $npmCmd) {
    throw "npm not found in PATH. Please install Node.js (LTS) and retry."
  }

  $nodeModules = Join-Path $Root 'frontend\node_modules'
  if (-not (Test-Path $nodeModules)) {
    Write-Host "[setup] Installing frontend deps..." -ForegroundColor Cyan
    Push-Location (Join-Path $Root 'frontend')
    try {
      & npm install
    } finally {
      Pop-Location
    }
  }
}

function Test-TcpPortAvailable {
  param(
    [Parameter(Mandatory = $true)]
    [int]$Port
  )

  $listeners = @()
  try {
    $addresses = @([System.Net.IPAddress]::Loopback)
    if ([System.Net.Sockets.Socket]::OSSupportsIPv6) {
      $addresses += [System.Net.IPAddress]::IPv6Loopback
    }

    foreach ($addr in $addresses) {
      $l = [System.Net.Sockets.TcpListener]::new($addr, $Port)
      $l.Start()
      $listeners += $l
    }

    return $true
  } catch {
    return $false
  } finally {
    foreach ($l in $listeners) {
      try { $l.Stop() } catch { }
    }
  }
}

function Find-FreeTcpPort {
  param(
    [int]$PreferredPort = 3000,
    [int]$MaxTries = 50
  )

  for ($p = $PreferredPort; $p -lt ($PreferredPort + $MaxTries); $p++) {
    if (Test-TcpPortAvailable -Port $p) {
      return $p
    }
  }

  throw "No free TCP port found in range $PreferredPort..$($PreferredPort + $MaxTries - 1)."
}

function Start-FrontendViteDev {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Root,
    [Parameter(Mandatory = $true)]
    [int]$Port,
    [switch]$OpenBrowser
  )

  $frontendDir = Join-Path $Root 'frontend'
  $viteCmd = Join-Path $frontendDir 'node_modules\.bin\vite.cmd'
  if (-not (Test-Path $viteCmd)) {
    throw "vite not found: $viteCmd. Run 'start.bat setup' first."
  }

  # Force IPv4 localhost so `localhost`/IPv6 listeners can't hijack the port.
  $args = @('--host', '127.0.0.1', '--port', "$Port", '--strictPort')
  if ($OpenBrowser) {
    $args += '--open'
  }

  Push-Location $frontendDir
  try {
    & $viteCmd @args
  } finally {
    Pop-Location
  }
}

function Run-Doctor {
  param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,
    [Parameter(Mandatory = $true)]
    [string]$Root
  )

  Write-Host "[doctor] python -m compileall . -q" -ForegroundColor Cyan
  Push-Location $Root
  try {
    & $PythonExe -m compileall . -q
    & $PythonExe -c "import backend.app, backend.mcp.stdio_server"
  } finally {
    Pop-Location
  }

  $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
  if ($npmCmd) {
    Ensure-FrontendDeps -Root $Root
    Write-Host "[doctor] npm run build" -ForegroundColor Cyan
    Push-Location (Join-Path $Root 'frontend')
    try {
      & npm run build
    } finally {
      Pop-Location
    }
  } else {
    Write-Host "[doctor] npm not found; skipping frontend build." -ForegroundColor Yellow
  }

  Write-Host "Smoke checks passed." -ForegroundColor Green
}

$Root = $PSScriptRoot
$cmd = ''
if ($null -ne $Command) {
  $cmd = $Command
}
$cmd = $cmd.Trim()
if (-not $cmd) { $cmd = 'dev' }
$cmdLower = $cmd.ToLowerInvariant()

if ($cmdLower -in @('help', '--help', '-h', '/?')) {
  Show-Usage
  exit 0
}

$needPython = $cmdLower -in @('dev', 'all', 'backend', 'mcp', 'setup', 'doctor')
$needFrontend = $cmdLower -in @('dev', 'all', 'frontend', 'setup')
$needDoctor = $cmdLower -eq 'doctor'

$pythonExe = $null
if ($needPython) {
  $pythonExe = Ensure-Venv -Root $Root
  Ensure-BackendDeps -PythonExe $pythonExe -Root $Root
}
if ($needFrontend) {
  Ensure-FrontendDeps -Root $Root
}

if ($cmdLower -eq 'setup') {
  Write-Host "Setup complete." -ForegroundColor Green
  exit 0
}

if ($needDoctor) {
  Run-Doctor -PythonExe $pythonExe -Root $Root
  exit 0
}

function Start-BackgroundProcess {
  param(
    [Parameter(Mandatory = $true)]
    [string]$FilePath,
    [Parameter(Mandatory = $true)]
    [string[]]$ArgumentList,
    [Parameter(Mandatory = $true)]
    [string]$WorkingDirectory,
    [Parameter(Mandatory = $true)]
    [string]$Name
  )

  Write-Host ("[run] Starting {0}..." -f $Name) -ForegroundColor Cyan
  $proc = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory -NoNewWindow -PassThru
  Start-Sleep -Milliseconds 500
  if ($proc.HasExited) {
    throw ("{0} exited immediately (exit code {1})." -f $Name, $proc.ExitCode)
  }
  return $proc
}

if ($cmdLower -eq 'backend') {
  Push-Location $Root
  try {
    & $pythonExe -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
  } finally {
    Pop-Location
  }
  exit 0
}

if ($cmdLower -eq 'mcp') {
  Push-Location $Root
  try {
    & $pythonExe -m backend.mcp.stdio_server
  } finally {
    Pop-Location
  }
  exit 0
}

if ($cmdLower -eq 'frontend') {
  Ensure-FrontendDeps -Root $Root
  $frontendPort = Find-FreeTcpPort -PreferredPort 3000 -MaxTries 50
  Write-Host ("Frontend dev will run on: http://127.0.0.1:{0}" -f $frontendPort) -ForegroundColor Green
  Start-FrontendViteDev -Root $Root -Port $frontendPort -OpenBrowser
  exit 0
}

if ($cmdLower -notin @('dev', 'all')) {
  Write-Host "[ERROR] Unknown command: $Command" -ForegroundColor Red
  Show-Usage
  exit 1
}

$backendProc = $null
$mcpProc = $null

try {
  $frontendPort = Find-FreeTcpPort -PreferredPort 3000 -MaxTries 50

  $backendProc = Start-BackgroundProcess `
    -FilePath $pythonExe `
    -ArgumentList @('-m', 'uvicorn', 'backend.app:app', '--host', '0.0.0.0', '--port', '8000', '--reload') `
    -WorkingDirectory $Root `
    -Name 'backend (8000)'

  if ($cmdLower -eq 'all') {
    $mcpProc = Start-BackgroundProcess `
      -FilePath $pythonExe `
      -ArgumentList @('-m', 'backend.mcp.stdio_server') `
      -WorkingDirectory $Root `
      -Name 'mcp'
  }

  Write-Host ""
  Write-Host "Backend API:   http://localhost:8000" -ForegroundColor Green
  Write-Host "API Docs:      http://localhost:8000/docs" -ForegroundColor Green
  Write-Host ("Frontend Dev:  http://127.0.0.1:{0}" -f $frontendPort) -ForegroundColor Green
  Write-Host "Tip: If 3000 is occupied, launcher auto-picks 3001/3002/... so the URL above is always correct." -ForegroundColor Yellow
  if ($cmdLower -eq 'all') {
    Write-Host "MCP:      python -m backend.mcp.stdio_server" -ForegroundColor Green   
  }
  Write-Host "Press Ctrl+C once to stop everything." -ForegroundColor Yellow    
  Write-Host ""

  Start-FrontendViteDev -Root $Root -Port $frontendPort -OpenBrowser
} finally {
  Write-Host ""
  Write-Host "[cleanup] Stopping background processes..." -ForegroundColor Cyan

  foreach ($p in @($mcpProc, $backendProc)) {
    if ($null -eq $p) { continue }
    try {
      if (-not $p.HasExited) {
        # Uvicorn --reload (and some other processes) may spawn child processes;
        # kill the whole process tree to avoid leaving strays.
        & taskkill /PID $p.Id /T /F *> $null
      }
    } catch {
      Write-Host ("[cleanup] Failed to stop PID {0}: {1}" -f $p.Id, $_.Exception.Message) -ForegroundColor Yellow
    }
  }
}
