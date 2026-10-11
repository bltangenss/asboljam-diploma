param([switch]$Install)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot
if (Test-Path -LiteralPath '.env') {
    foreach ($line in Get-Content -LiteralPath '.env' -Encoding UTF8) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $name = $Matches[1]
            $value = $Matches[2].Trim().Trim('"').Trim("'")
            if ($value -and -not [Environment]::GetEnvironmentVariable($name,'Process')) {
                [Environment]::SetEnvironmentVariable($name,$value,'Process')
            }
        }
    }
}
if ($Install) {
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Python venv creation failed.' }
    }
    & '.venv/Scripts/python.exe' -m pip install -r requirements.lock
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Node dependency installation failed.' }
}
$pythonPath = if (Test-Path -LiteralPath '.venv/Scripts/python.exe') { (Resolve-Path -LiteralPath '.venv/Scripts/python.exe').Path } else { (Get-Command python -ErrorAction Stop).Source }
$nodePath = (Get-Command node -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath 'node_modules/vite/bin/vite.js')) { throw 'Run .\scripts\start.ps1 -Install first.' }
foreach ($port in @(8000,3000)) {
    $probe = [Net.Sockets.TcpClient]::new()
    try { $probe.Connect('127.0.0.1',$port); throw "Port $port is already in use. Stop the previous server first." }
    catch [Net.Sockets.SocketException] { }
    finally { $probe.Dispose() }
}
& $pythonPath -X utf8 database/migrate.py
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
& $pythonPath -X utf8 scripts/seed_demo.py
if ($LASTEXITCODE -ne 0) { throw 'Demo seed failed.' }
$logRoot = Join-Path $projectRoot '.cache/logs'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
$processes = @()
try {
    $specs = @(
        @{ Name='api'; File=$pythonPath; Arguments='-X utf8 -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000 --no-access-log' },
        @{ Name='worker'; File=$pythonPath; Arguments='-X utf8 -m apps.worker.main' },
        @{ Name='web'; File=$nodePath; Arguments='node_modules/vite/bin/vite.js --host 127.0.0.1 --port 3000' }
    )
    foreach ($spec in $specs) {
        $process = Start-Process -FilePath $spec.File -ArgumentList $spec.Arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logRoot ($spec.Name+'.log')) -RedirectStandardError (Join-Path $logRoot ($spec.Name+'.err.log'))
        $processes += @{ name=$spec.Name; id=$process.Id; started_at=$process.StartTime.ToUniversalTime().ToString('o') }
    }
    $processes | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $projectRoot '.cache/processes.json') -Encoding UTF8
    Start-Sleep -Seconds 2
    foreach ($item in $processes) {
        if (-not (Get-Process -Id $item.id -ErrorAction SilentlyContinue)) { throw "Process $($item.name) exited; read .cache/logs." }
    }
    Write-Host 'AsBoljam started: http://localhost:3000'
    Write-Host 'API documentation: http://127.0.0.1:8000/docs'
    Write-Host 'Logs: .cache/logs. Stop with .\scripts\stop.ps1.'
} catch {
    foreach ($item in $processes) { Stop-Process -Id $item.id -ErrorAction SilentlyContinue }
    throw
}
