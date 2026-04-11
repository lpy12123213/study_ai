param(
  [Parameter(Position = 0)]
  [string]$Command = 'dev'
)

$ErrorActionPreference = 'Stop'

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

$root = $PSScriptRoot
$python = Resolve-SystemPython
$script = Join-Path $root 'scripts\start.py'

& $python $script $Command @args
exit $LASTEXITCODE

