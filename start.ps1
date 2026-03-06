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

function Get-ContentFingerprint {
  param(
    [Parameter(Mandatory = $true)]
    [string[]]$Paths
  )

  $sha = [System.Security.Cryptography.SHA256]::Create()
  try {
    $builder = New-Object System.Text.StringBuilder
    foreach ($path in $Paths) {
      if (-not (Test-Path $path)) { continue }
      $resolved = (Resolve-Path $path).Path
      [void]$builder.AppendLine("## $resolved")
      [void]$builder.AppendLine([System.IO.File]::ReadAllText($resolved))
    }
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($builder.ToString())
    $hash = $sha.ComputeHash($bytes)
    return ([System.BitConverter]::ToString($hash)).Replace('-', '').ToLowerInvariant()
  } finally {
    $sha.Dispose()
  }
}

function Read-Stamp {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path
  )

  if (-not (Test-Path $Path)) {
    return ''
  }
  return (Get-Content $Path -Raw).Trim()
}

function Write-Stamp {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [Parameter(Mandatory = $true)]
    [string]$Value
  )

  $dir = Split-Path -Parent $Path
  if ($dir -and -not (Test-Path $dir)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
  }
  Set-Content -Path $Path -Value $Value -Encoding utf8
}

function Invoke-CheckedNative {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Label,
    [Parameter(Mandatory = $true)]
    [string]$FilePath,
    [string[]]$ArgumentList = @(),
    [string]$WorkingDirectory = ""
  )

  $previous = $null
  if ($WorkingDirectory) {
    $previous = Get-Location
    Push-Location $WorkingDirectory
  }

  try {
    & $FilePath @ArgumentList
    $exitCode = $LASTEXITCODE
  } finally {
    if ($previous) {
      Pop-Location
    }
  }

  if ($exitCode -ne 0) {
    throw ("{0} failed with exit code {1}" -f $Label, $exitCode)
  }
}

function Ensure-BackendDeps {
  param(
    [Parameter(Mandatory = $true)]
    [string]$PythonExe,
    [Parameter(Mandatory = $true)]
    [string]$Root
  )

  Write-Host "[setup] Checking backend deps..." -ForegroundColor Cyan

  $requirementsFiles = @(
    (Join-Path $Root 'requirements.txt')
  )
  $requirementsDev = Join-Path $Root 'requirements-dev.txt'
  if (Test-Path $requirementsDev) {
    $requirementsFiles += $requirementsDev
  }

  $requirementsStamp = Join-Path $Root 'venv\.backend-requirements.sha256'
  $expectedFingerprint = Get-ContentFingerprint -Paths $requirementsFiles
  $installedFingerprint = Read-Stamp -Path $requirementsStamp

  if ($expectedFingerprint -ne $installedFingerprint) {
    Write-Host "[setup] Installing backend Python packages..." -ForegroundColor Cyan
    Invoke-CheckedNative -Label 'pip install bootstrap tools' -FilePath $PythonExe -ArgumentList @('-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel')
    Invoke-CheckedNative -Label 'pip install requirements.txt' -FilePath $PythonExe -ArgumentList @('-m', 'pip', 'install', '-r', (Join-Path $Root 'requirements.txt'))
    if (Test-Path $requirementsDev) {
      Invoke-CheckedNative -Label 'pip install requirements-dev.txt' -FilePath $PythonExe -ArgumentList @('-m', 'pip', 'install', '-r', $requirementsDev)
    }
    Write-Stamp -Path $requirementsStamp -Value $expectedFingerprint
  }

  $oldEap = $ErrorActionPreference
  $ErrorActionPreference = 'SilentlyContinue'
  & $PythonExe -m playwright --version *> $null
  $playwrightVersionExit = $LASTEXITCODE
  $ErrorActionPreference = $oldEap

  if ($playwrightVersionExit -ne 0) {
    Invoke-CheckedNative -Label 'pip install playwright' -FilePath $PythonExe -ArgumentList @('-m', 'pip', 'install', 'playwright')
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

  $frontendDir = Join-Path $Root 'frontend'
  $nodeModules = Join-Path $frontendDir 'node_modules'
  $frontendFiles = @(
    (Join-Path $frontendDir 'package.json')
  )
  $packageLock = Join-Path $frontendDir 'package-lock.json'
  if (Test-Path $packageLock) {
    $frontendFiles += $packageLock
  }
  $depsStamp = Join-Path $frontendDir 'node_modules\.deps.sha256'
  $expectedFingerprint = Get-ContentFingerprint -Paths $frontendFiles
  $installedFingerprint = Read-Stamp -Path $depsStamp

  if ((-not (Test-Path $nodeModules)) -or $expectedFingerprint -ne $installedFingerprint) {
    Write-Host "[setup] Installing frontend deps..." -ForegroundColor Cyan
    Push-Location $frontendDir
    try {
      Invoke-CheckedNative -Label 'npm install' -FilePath 'npm' -ArgumentList @('install')
      Write-Stamp -Path $depsStamp -Value $expectedFingerprint
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
  Invoke-CheckedNative -Label 'python -m compileall' -FilePath $PythonExe -ArgumentList @('-m', 'compileall', '.', '-q') -WorkingDirectory $Root
  Write-Host "[doctor] python -c `"import backend.app, backend.mcp.stdio_server, mcp_server.server`"" -ForegroundColor Cyan
  Invoke-CheckedNative -Label 'python import check' -FilePath $PythonExe -ArgumentList @('-c', 'import backend.app, backend.mcp.stdio_server, mcp_server.server') -WorkingDirectory $Root
  Write-Host "[doctor] python -m pip check" -ForegroundColor Cyan
  Invoke-CheckedNative -Label 'python -m pip check' -FilePath $PythonExe -ArgumentList @('-m', 'pip', 'check') -WorkingDirectory $Root
  Write-Host "[doctor] python -m unittest discover -s backend/tests -p `"test_*.py`"" -ForegroundColor Cyan
  Invoke-CheckedNative -Label 'python -m unittest discover' -FilePath $PythonExe -ArgumentList @('-m', 'unittest', 'discover', '-s', 'backend/tests', '-p', 'test_*.py') -WorkingDirectory $Root
  $ruffTargets = @(
    'backend/api/chat.py',
    'backend/api/media.py',
    'backend/api/papers.py',
    'backend/api/subjects.py',
    'backend/api/canvas.py',
    'backend/api/study_materials.py',
    'backend/chat/llm_mixin.py',
    'backend/chat/service.py',
    'backend/core/plot_tools.py',
    'backend/database/repositories/papers.py',
    'backend/study_materials/task_manager.py',
    'backend/paper_compose/workflow.py',
    'backend/tests'
  )
  Write-Host "[doctor] python -m ruff check <maintained backend paths>" -ForegroundColor Cyan
  $ruffArgs = @('-m', 'ruff', 'check') + $ruffTargets
  Invoke-CheckedNative -Label 'python -m ruff check maintained backend paths' -FilePath $PythonExe -ArgumentList $ruffArgs -WorkingDirectory $Root

  $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
  if ($npmCmd) {
    Ensure-FrontendDeps -Root $Root
    Write-Host "[doctor] npm run lint" -ForegroundColor Cyan
    Invoke-CheckedNative -Label 'npm run lint' -FilePath 'npm' -ArgumentList @('run', 'lint') -WorkingDirectory (Join-Path $Root 'frontend')
    Write-Host "[doctor] npm run build" -ForegroundColor Cyan
    Invoke-CheckedNative -Label 'npm run build' -FilePath 'npm' -ArgumentList @('run', 'build') -WorkingDirectory (Join-Path $Root 'frontend')
  } else {
    Write-Host "[doctor] npm not found; skipping frontend build." -ForegroundColor Yellow
  }

  Write-Host "Doctor checks passed." -ForegroundColor Green
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
