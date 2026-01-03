param(
  [Parameter(Position = 0)]
  [string]$Command = 'dev'
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Inner = Join-Path $RepoRoot 'exam_paper_assistant\start.ps1'

if (-not (Test-Path $Inner)) {
  throw "Cannot find launcher: $Inner"
}

& $Inner $Command
