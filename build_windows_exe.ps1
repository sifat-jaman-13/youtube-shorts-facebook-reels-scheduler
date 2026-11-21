$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path $compiler)) {
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
}
if (-not (Test-Path $compiler)) {
    throw 'The .NET Framework C# compiler (csc.exe) was not found. Run this build on Windows with .NET Framework 4.x installed.'
}
$dist = Join-Path $root 'dist'
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$output = Join-Path $dist 'ScarClipScheduler.exe'
$arguments = @(
    '/nologo',
    '/target:exe',
    '/platform:anycpu',
    "/out:$output",
    "/resource:$(Join-Path $root 'app.py'),ScarClipScheduler.app.py",
    "/resource:$(Join-Path $root 'requirements.txt'),ScarClipScheduler.requirements.txt",
    (Join-Path $root 'bootstrapper\Program.cs')
)
Write-Host 'Building the self-contained ScarClipScheduler terminal bootstrapper...'
& $compiler @arguments
if ($LASTEXITCODE -ne 0) {
    throw "C# compilation failed with exit code $LASTEXITCODE."
}
if (-not (Test-Path $output)) {
    throw 'The compiler returned successfully but the EXE file was not created.'
}
Write-Host "Built: $output"
Get-Item $output | Select-Object FullName, Length, LastWriteTime | Format-List
