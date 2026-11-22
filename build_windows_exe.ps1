$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$project = Join-Path $root 'native\ScarClipScheduler.Wpf\ScarClipScheduler.Wpf.csproj'
$publish = Join-Path $root 'dist\package'
$installerDir = Join-Path $root 'dist\installer'
$installerExe = Join-Path $installerDir 'ScarClipScheduler-Setup.exe'

if (Test-Path $publish) {
    Remove-Item -LiteralPath $publish -Recurse -Force
}
if (Test-Path $installerDir) {
    Remove-Item -LiteralPath $installerDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $publish, $installerDir | Out-Null

Write-Host 'Publishing ScarClipScheduler 2.0.14 (self-contained native WPF)...' -ForegroundColor Cyan
$arguments = @(
    'publish', $project,
    '-c', 'Release',
    '-r', 'win-x64',
    '--self-contained', 'true',
    '-p:PublishSingleFile=true',
    '-p:IncludeNativeLibrariesForSelfExtract=true',
    '-p:EnableCompressionInSingleFile=true',
    '-p:DebugType=None',
    '-p:DebugSymbols=false',
    '-o', $publish
)
dotnet @arguments
if ($LASTEXITCODE -ne 0) {
    throw "WPF publish failed with exit code $LASTEXITCODE."
}

$exe = Join-Path $publish 'ScarClipScheduler.exe'
$backend = Join-Path $publish 'backend\backend_service.py'
$workerSource = Join-Path $publish 'backend\app.py'
$requirements = Join-Path $publish 'backend\requirements.txt'
$setupScript = Join-Path $publish 'Install-ScarClipScheduler.ps1'
$installNotes = Join-Path $publish 'README-INSTALL.txt'

if (-not (Test-Path $exe)) { throw 'Native WPF executable was not produced.' }
if (-not (Test-Path $backend)) { throw 'Background publishing worker was not packaged.' }
if (-not (Test-Path $workerSource)) { throw 'Publishing engine source was not packaged.' }
if (-not (Test-Path $requirements)) { throw 'Publishing-worker requirements were not packaged.' }

Copy-Item -LiteralPath (Join-Path $root 'Install-ScarClipScheduler.ps1') -Destination $setupScript -Force
Copy-Item -LiteralPath (Join-Path $root 'README-INSTALL.txt') -Destination $installNotes -Force
Copy-Item -LiteralPath (Join-Path $root 'LICENSE') -Destination (Join-Path $publish 'LICENSE') -Force

$iscc = $null
$candidates = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
) | Where-Object { $_ }
foreach ($candidate in $candidates) {
    if (Test-Path $candidate) { $iscc = $candidate; break }
}
if (-not $iscc) {
    $command = Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue
    if ($command) { $iscc = $command.Source }
}
if (-not $iscc) {
    throw 'Inno Setup 6 is required to build the Windows installer. Install it from https://jrsoftware.org/isdl.php and rerun this script.'
}

Write-Host 'Compiling the standalone Windows setup EXE...' -ForegroundColor Cyan
$iss = Join-Path $root 'installer\ScarClipScheduler.iss'
& $iscc $iss
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup compilation failed with exit code $LASTEXITCODE."
}
if (-not (Test-Path $installerExe)) {
    throw 'The installer compiler finished without producing ScarClipScheduler-Setup.exe.'
}

# Retain the self-contained app executable as a local developer artifact only.
Copy-Item -LiteralPath $exe -Destination (Join-Path $root 'dist\ScarClipScheduler.exe') -Force

Write-Host ''
Write-Host 'Windows installer build complete.' -ForegroundColor Green
Get-Item $installerExe, $exe, $backend, $requirements |
    Select-Object FullName, Length |
    Format-Table -AutoSize
