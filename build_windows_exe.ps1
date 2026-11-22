$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$project = Join-Path $root 'native\ScarClipScheduler.Wpf\ScarClipScheduler.Wpf.csproj'
$publish = Join-Path $root 'dist\package'
$zip = Join-Path $root 'dist\ScarClipScheduler-Windows-x64.zip'

if (Test-Path $publish) {
    Remove-Item -LiteralPath $publish -Recurse -Force
}
if (Test-Path $zip) {
    Remove-Item -LiteralPath $zip -Force
}
New-Item -ItemType Directory -Force -Path $publish | Out-Null

Write-Host 'Publishing ScarClipScheduler 2.0.2 (native WPF, self-contained .NET 10)...'
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
$requirements = Join-Path $publish 'backend\requirements.txt'
$workerSource = Join-Path $publish 'backend\app.py'
$setup = Join-Path $publish 'Install-ScarClipScheduler.ps1'
if (-not (Test-Path $exe)) { throw 'Native WPF EXE was not produced.' }
if (-not (Test-Path $backend)) { throw 'Background publishing worker was not packaged.' }
if (-not (Test-Path $workerSource)) { throw 'Publishing engine source was not packaged.' }
if (-not (Test-Path $requirements)) { throw 'Backend requirements were not packaged.' }

Copy-Item -LiteralPath (Join-Path $root 'Install-ScarClipScheduler.ps1') -Destination $setup -Force
Copy-Item -LiteralPath (Join-Path $root 'README-INSTALL.txt') -Destination (Join-Path $publish 'README-INSTALL.txt') -Force

# Keep a convenient local EXE output, but publish the complete application as a ZIP.
Copy-Item -LiteralPath $exe -Destination (Join-Path $root 'dist\ScarClipScheduler.exe') -Force
Compress-Archive -Path (Join-Path $publish '*') -DestinationPath $zip -CompressionLevel Optimal -Force

Write-Host 'Native WPF package build complete.'
Get-Item $exe, $zip, $backend, $requirements | Select-Object FullName, Length | Format-Table -AutoSize
