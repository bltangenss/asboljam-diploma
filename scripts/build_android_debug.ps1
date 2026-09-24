param(
    [string]$JavaHome = '',
    [string]$AndroidSdk = '',
    [ValidateSet('x86', 'x86_64', 'arm64-v8a', 'armeabi-v7a')]
    [string]$Architecture = 'x86',
    [ValidateRange(768, 4096)]
    [int]$HeapMegabytes = 1536
)

# Build only. This script never launches/wipes an emulator or publishes a package.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$mobileRoot = Join-Path $projectRoot 'apps/mobile'
$reportPath = Join-Path $projectRoot 'artifacts/verification/android-build.json'
$logRoot = Join-Path $projectRoot '.cache/logs'
$report = [ordered]@{
    started_at_utc = [DateTime]::UtcNow.ToString('o')
    status = 'not_started'
    architecture = $Architecture
    variant = 'debug development client; requires Metro for app JavaScript'
    device_tested = $false
}

if (-not $JavaHome) {
    $jdk21 = Join-Path $env:ProgramFiles 'Java/jdk-21'
    $JavaHome = if (Test-Path -LiteralPath (Join-Path $jdk21 'bin/java.exe')) { $jdk21 } else { $env:JAVA_HOME }
}
if (-not $AndroidSdk) {
    $AndroidSdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { Join-Path $env:LOCALAPPDATA 'Android/Sdk' }
}
if (-not $JavaHome -or -not (Test-Path -LiteralPath (Join-Path $JavaHome 'bin/java.exe'))) {
    throw 'Pass -JavaHome pointing to an installed JDK 17 or 21.'
}
if (-not (Test-Path -LiteralPath $AndroidSdk -PathType Container)) {
    throw 'Pass -AndroidSdk pointing to the installed Android SDK.'
}
if (-not (Test-Path -LiteralPath (Join-Path $mobileRoot 'node_modules/expo/bin/cli'))) {
    throw 'Install the locked mobile dependencies before building: cd apps/mobile; npm ci'
}
Get-Command node.exe -ErrorAction Stop | Out-Null
$ErrorActionPreference = 'Continue'
$javaVersion = (& (Join-Path $JavaHome 'bin/java.exe') -version 2>&1 | Out-String)
$javaExitCode = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
if ($javaExitCode -ne 0 -or $javaVersion -notmatch 'version "(17|21)[.+"]') {
    throw 'Use JDK 17/21 for this pinned Gradle build; pass -JavaHome for one of those installed versions.'
}
$report.java_major = [int]$Matches[1]
$freeBytes = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($projectRoot)).AvailableFreeSpace
if ($freeBytes -lt 8GB) { throw 'At least 8 GiB of free project-drive space is required for the first native build.' }
$report.free_disk_gib_before = [Math]::Round($freeBytes / 1GB, 2)

$environmentNames = @('JAVA_HOME', 'ANDROID_HOME', 'ANDROID_SDK_ROOT', 'CI', 'EXPO_NO_TELEMETRY', 'CMAKE_BUILD_PARALLEL_LEVEL')
$previousEnvironment = @{}
foreach ($name in $environmentNames) { $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path -Parent $reportPath) -Force | Out-Null

Push-Location $mobileRoot
try {
    $env:JAVA_HOME = $JavaHome
    $env:ANDROID_HOME = $AndroidSdk
    $env:ANDROID_SDK_ROOT = $AndroidSdk
    $env:CI = '1'
    $env:EXPO_NO_TELEMETRY = '1'
    $env:CMAKE_BUILD_PARALLEL_LEVEL = '1'
    $report.status = 'running'
    $report.phase = 'expo_prebuild'
    # Windows PowerShell maps native stderr to ErrorRecords even for exit code 0.
    $ErrorActionPreference = 'Continue'
    & node.exe './node_modules/expo/bin/cli' prebuild --platform android --no-install 2>&1 | Tee-Object -FilePath (Join-Path $logRoot 'android-prebuild.log')
    $prebuildExitCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($prebuildExitCode -ne 0) { throw 'Expo prebuild failed; inspect .cache/logs/android-prebuild.log.' }

    Set-Location (Join-Path $mobileRoot 'android')
    $report.phase = 'gradle_assemble_debug'
    $gradleArguments = @(
        ':app:assembleDebug', '--no-daemon', '--max-workers=1', '--no-configuration-cache',
        '-Dorg.gradle.parallel=false', '-Dorg.gradle.vfs.watch=false',
        "-Dorg.gradle.jvmargs=-Xmx${HeapMegabytes}m -XX:MaxMetaspaceSize=512m -Dfile.encoding=UTF-8",
        '-Pkotlin.compiler.execution.strategy=in-process', "-PreactNativeArchitectures=$Architecture", '--console=plain'
    )
    $ErrorActionPreference = 'Continue'
    & '.\gradlew.bat' @gradleArguments 2>&1 | Tee-Object -FilePath (Join-Path $logRoot 'android-build.log')
    $gradleExitCode = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($gradleExitCode -ne 0) { throw 'Gradle build failed; inspect .cache/logs/android-build.log.' }

    $apkRelative = 'apps/mobile/android/app/build/outputs/apk/debug/app-debug.apk'
    $apk = Join-Path $projectRoot $apkRelative
    if (-not (Test-Path -LiteralPath $apk -PathType Leaf)) { throw 'Gradle succeeded but the expected debug APK is missing.' }
    $report.status = 'passed'
    $report.phase = 'apk_created'
    $report.apk = $apkRelative
    $report.bytes = (Get-Item -LiteralPath $apk).Length
    $report.sha256 = (Get-FileHash -LiteralPath $apk -Algorithm SHA256).Hash.ToLowerInvariant()
} catch {
    $report.status = 'failed'
    throw
} finally {
    Pop-Location
    foreach ($name in $environmentNames) { [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process') }
    $report.finished_at_utc = [DateTime]::UtcNow.ToString('o')
    $report | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $reportPath -Encoding UTF8
}
Write-Output ('Debug APK built: ' + $report.apk)
Write-Output ('SHA256: ' + $report.sha256)
