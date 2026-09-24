$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pidFile = Join-Path $projectRoot '.cache/processes.json'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Host 'No saved AsBoljam processes.'; exit 0 }
foreach ($item in (Get-Content -LiteralPath $pidFile -Raw -Encoding UTF8 | ConvertFrom-Json)) {
    $process = Get-Process -Id $item.id -ErrorAction SilentlyContinue
    $savedTime = ([datetime]$item.started_at).ToUniversalTime()
    if ($process -and $process.StartTime.ToUniversalTime().Ticks -eq $savedTime.Ticks) {
        Stop-Process -Id $process.Id
        Write-Host "Stopped $($item.name)."
    }
}
