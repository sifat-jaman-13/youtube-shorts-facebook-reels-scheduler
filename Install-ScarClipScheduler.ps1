$ErrorActionPreference = 'Stop'

# Persist setup diagnostics in the user's data folder, not beside the program.
$dataDir = Join-Path $env:LOCALAPPDATA 'ScarClipScheduler'
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$setupLog = Join-Path $dataDir 'installer-setup.log'
$transcriptStarted = $false
try {
    Start-Transcript -Path $setupLog -Append -Force | Out-Null
    $transcriptStarted = $true
} catch {
    Write-Host "Warning: could not start setup transcript: $($_.Exception.Message)" -ForegroundColor Yellow
}

trap {
    $setupError = $_
    Write-Host ''
    Write-Host 'SCARCLIPSCHEDULER SETUP FAILED' -ForegroundColor Red
    Write-Host $setupError.Exception.Message -ForegroundColor Red
    Write-Host "Detailed setup log: $setupLog" -ForegroundColor Yellow
    if ($transcriptStarted) {
        try { Stop-Transcript | Out-Null } catch { }
    }
    Read-Host 'Press Enter to close this setup window'
    exit 1
}

$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$install = Join-Path $env:LOCALAPPDATA 'Programs\ScarClipScheduler'
$dataDir = Join-Path $env:LOCALAPPDATA 'ScarClipScheduler'
$pythonVenv = Join-Path $install '.venv\Scripts\python.exe'
$requirements = Join-Path $install 'backend\requirements.txt'
$dependencyMarker = Join-Path $install '.dependencies-version'
$exe = Join-Path $install 'ScarClipScheduler.exe'

function Invoke-CapturedProcess([string]$FilePath, [string[]]$Arguments = @()) {
    # Capture native exit codes without PowerShell 5.1 treating an expected
    # missing-version result as a terminating error.
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    $quoted = foreach ($argument in $Arguments) {
        if ($argument -notmatch '[\s"]') {
            $argument
        } else {
            $escaped = $argument -replace '(\\*)"', '$1$1\"'
            $escaped = $escaped -replace '(\\+)$', '$1$1'
            '"' + $escaped + '"'
        }
    }
    $startInfo.Arguments = ($quoted -join ' ')
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    if (-not $process.Start()) { throw "Could not start native process: $FilePath" }
    $stdout = $process.StandardOutput.ReadToEndAsync()
    $stderr = $process.StandardError.ReadToEndAsync()
    $process.WaitForExit()
    return [pscustomobject]@{ ExitCode = $process.ExitCode; StdOut = $stdout.Result; StdErr = $stderr.Result }
}

function Test-SupportedPython([string]$Python) {
    if (-not $Python -or -not (Test-Path -LiteralPath $Python -PathType Leaf)) { return $false }
    $checkCode = 'import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] <= (3,12) and sys.maxsize > 2**32 else 2)'
    try {
        $result = Invoke-CapturedProcess -FilePath $Python -Arguments @('-c', $checkCode)
        return ($result.ExitCode -eq 0)
    } catch { return $false }
}

function Get-PythonCommand {
    $candidatePaths = New-Object System.Collections.Generic.List[string]
    # Use one successful launcher listing instead of probing an absent version
    # with py -3.12, which can abort Windows PowerShell 5.1 under ErrorActionPreference=Stop.
    $launcher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $listing = Invoke-CapturedProcess -FilePath $launcher.Source -Arguments @('-0p')
            if ($listing.ExitCode -eq 0) {
                foreach ($line in ($listing.StdOut -split [Environment]::NewLine)) {
                    if ($line -match '^\s*-V:(?<version>3\.(?:12|11))(?:\s+\*)?\s+(?<path>.+?pythonw?\.exe)\s*$') {
                        $candidatePaths.Add($Matches['path'].Trim())
                    }
                }
            }
        } catch { Write-Host "Python launcher listing was unavailable: $($_.Exception.Message)" -ForegroundColor Yellow }
    }
    # Standard python.org locations and PATH are fallbacks if the launcher is unavailable.
    $candidatePaths.Add((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'))
    $candidatePaths.Add((Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'))
    $candidatePaths.Add((Join-Path $env:ProgramFiles 'Python312\python.exe'))
    $candidatePaths.Add((Join-Path $env:ProgramFiles 'Python311\python.exe'))
    $candidatePaths.Add('C:\Python312\python.exe')
    $candidatePaths.Add('C:\Python311\python.exe')
    $pythonCommand = Get-Command 'python.exe' -ErrorAction SilentlyContinue
    if ($pythonCommand) { $candidatePaths.Add($pythonCommand.Source) }
    $seen = @{}
    foreach ($candidate in $candidatePaths) {
        if (-not $candidate) { continue }
        $fullPath = [IO.Path]::GetFullPath($candidate)
        if ($seen.ContainsKey($fullPath)) { continue }
        $seen[$fullPath] = $true
        if (Test-SupportedPython $fullPath) {
            $versionResult = Invoke-CapturedProcess -FilePath $fullPath -Arguments @('-c', 'import sys; print(".".join(map(str,sys.version_info[:2])))')
            return [pscustomobject]@{ File = $fullPath; Prefix = @(); Executable = $fullPath; Version = $versionResult.StdOut.Trim() }
        }
    }
    return $null
}
function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $current = $env:Path
    $env:Path = (@($machine, $user, $current) | Where-Object { $_ }) -join ';'
}

Write-Host ''
Write-Host 'ScarClipScheduler 2.0.5 — installation checks' -ForegroundColor Cyan
Write-Host 'This setup check runs during installation, not when you launch the app.' -ForegroundColor Gray
Write-Host ''

$existing = Get-Process -Name 'ScarClipScheduler' -ErrorAction SilentlyContinue
if ($existing) {
    throw 'ScarClipScheduler is already running. Click Quit in the app, allow active publishing work to finish, then rerun the installer.'
}

if (-not (Test-Path (Join-Path $source 'ScarClipScheduler.exe'))) {
    throw 'ScarClipScheduler.exe was not found beside the setup script. Run the official ScarClipScheduler-Setup.exe installer.'
}
if (-not (Test-Path (Join-Path $source 'backend\backend_service.py'))) {
    throw 'The backend folder is missing. Re-run the official installer.'
}
if (-not (Test-Path $requirements)) {
    throw "Publishing-worker requirements were not found: $requirements"
}

New-Item -ItemType Directory -Force -Path $install | Out-Null

$sourceFull = [IO.Path]::GetFullPath($source).TrimEnd('\')
$installFull = [IO.Path]::GetFullPath($install).TrimEnd('\')
if (-not [string]::Equals($sourceFull, $installFull, [StringComparison]::OrdinalIgnoreCase)) {
    Write-Host 'Copying ScarClipScheduler program files...' -ForegroundColor Gray
    Copy-Item -LiteralPath (Join-Path $source 'ScarClipScheduler.exe') -Destination $exe -Force
    $targetBackend = Join-Path $install 'backend'
    if (Test-Path $targetBackend) {
        Remove-Item -LiteralPath $targetBackend -Recurse -Force
    }
    Copy-Item -LiteralPath (Join-Path $source 'backend') -Destination $targetBackend -Recurse -Force
    $requirements = Join-Path $install 'backend\requirements.txt'
}

# Keep an existing compatible worker runtime. Recreate it only if its Python is
# outside the versions tested by the project (3.11 and 3.12, 64-bit).
if (Test-Path $pythonVenv) {
    if (-not (Test-SupportedPython $pythonVenv)) {
        Write-Host 'The existing worker runtime is not a supported Python 3.11/3.12 environment. Recreating it...' -ForegroundColor Yellow
        Remove-Item -LiteralPath (Join-Path $install '.venv') -Recurse -Force
    }
}

if (-not (Test-Path $pythonVenv)) {
    $python = Get-PythonCommand
    if (-not $python) {
        $winget = Get-Command 'winget.exe' -ErrorAction SilentlyContinue
        if (-not $winget) {
            Start-Process 'https://www.python.org/downloads/windows/'
            throw '64-bit Python 3.11 or 3.12 was not found and WinGet is unavailable. Install Python 3.12, reopen the installer, and try again.'
        }

        Write-Host 'No supported Python was found. Installing Python 3.12 for the current Windows user...' -ForegroundColor Yellow
        & $winget.Source install --id Python.Python.3.12 --exact --source winget --scope user --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            throw "WinGet could not install Python 3.12 (exit code $LASTEXITCODE)."
        }
        Refresh-ProcessPath
        $python = Get-PythonCommand
        if (-not $python) {
            $knownPython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
            if (Test-SupportedPython $knownPython) {
                $python = [pscustomobject]@{
                    File = $knownPython
                    Prefix = @()
                    Executable = $knownPython
                    Version = '3.12'
                }
            }
        }
        if (-not $python) {
            throw 'Python 3.12 installation completed but its executable could not be found. Reopen Windows PowerShell and run the installer again.'
        }
    }

    Write-Host "Using Python $($python.Version): $($python.Executable)" -ForegroundColor Green
    Write-Host 'Creating the isolated publishing-worker environment...' -ForegroundColor Gray
    $venvArgs = @($python.Prefix) + @('-m', 'venv', (Join-Path $install '.venv'))
    & $python.File @venvArgs
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $pythonVenv)) {
        throw 'Could not create the isolated Python environment.'
    }
}

# The installer verifies the venv and requirements fingerprint. It installs
# packages only if this is a first setup, requirements changed, or a health
# check fails. Normal app launches never execute this script.
$requirementsHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash.ToLowerInvariant()
$savedHash = if (Test-Path $dependencyMarker) { (Get-Content -LiteralPath $dependencyMarker -Raw).Trim() } else { '' }
$dependenciesReady = $false

if ($savedHash -eq $requirementsHash -and (Test-SupportedPython $pythonVenv)) {
    Write-Host 'Checking the existing publishing-worker packages...' -ForegroundColor Gray
    & $pythonVenv -m pip check
    if ($LASTEXITCODE -eq 0) {
        & $pythonVenv -c 'import requests, googleapiclient, google.auth, google_auth_oauthlib, google_auth_httplib2, tzdata' 2>$null
        if ($LASTEXITCODE -eq 0) {
            $dependenciesReady = $true
        }
    }
}

if ($dependenciesReady) {
    Write-Host 'Required Python packages are already installed and healthy. Skipping package installation.' -ForegroundColor Green
} else {
    Write-Host 'Installing or repairing publishing-worker dependencies...' -ForegroundColor Yellow
    & $pythonVenv -m pip install --disable-pip-version-check --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'Could not update pip.' }
    & $pythonVenv -m pip install --disable-pip-version-check --prefer-binary -r $requirements
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the publishing-worker dependencies.' }
    & $pythonVenv -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'The installed Python dependencies are inconsistent.' }
    & $pythonVenv -c 'import requests, googleapiclient, google.auth, google_auth_oauthlib, google_auth_httplib2, tzdata'
    if ($LASTEXITCODE -ne 0) { throw 'A required publishing dependency could not be imported after installation.' }
    Set-Content -LiteralPath $dependencyMarker -Value $requirementsHash -Encoding ASCII
    Write-Host 'Publishing-worker dependencies are installed and verified.' -ForegroundColor Green
}

# Keep the queue database and credentials in their separate user-data folder.
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

# Create/update a Start Menu shortcut (safe to call again during app updates).
$startMenu = [Environment]::GetFolderPath('Programs')
$shortcutPath = Join-Path $startMenu 'ScarClipScheduler.lnk'
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = $install
$shortcut.Description = 'ScarClipScheduler - YouTube Shorts and Facebook Page Reels'
$shortcut.Save()

Write-Host ''
Write-Host 'ScarClipScheduler setup completed successfully.' -ForegroundColor Green
Write-Host "Application: $exe"
Write-Host "User data:   $dataDir"
Write-Host 'Your queue database, scheduled-post records, settings, and platform credentials were not removed.' -ForegroundColor Gray
Write-Host "Setup log:   $setupLog" -ForegroundColor Gray
Write-Host ''
if ($transcriptStarted) { Stop-Transcript | Out-Null }
$startNow = Read-Host 'Start ScarClipScheduler now? (Y/N)'
if ($startNow -match '^(y|yes)$') {
    Start-Process -FilePath $exe -WorkingDirectory $install
}
