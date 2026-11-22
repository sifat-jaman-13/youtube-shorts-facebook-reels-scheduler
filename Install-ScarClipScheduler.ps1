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
    # 64-bit final CPython 3.10 or newer. There is intentionally no upper version cap.
    $checkCode = 'import sys; raise SystemExit(0 if sys.implementation.name == "cpython" and sys.version_info >= (3,10) and sys.version_info.releaselevel == "final" and sys.maxsize > 2**32 else 2)'
    try {
        $result = Invoke-CapturedProcess -FilePath $Python -Arguments @('-c', $checkCode)
        return ($result.ExitCode -eq 0)
    } catch { return $false }
}

function Get-PythonCommand {
    $candidatePaths = New-Object System.Collections.Generic.List[string]
    # Enumerate every installed interpreter once. This works with py.exe even
    # when one requested version (such as 3.12) is absent.
    $launcher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($launcher) {
        try {
            $listing = Invoke-CapturedProcess -FilePath $launcher.Source -Arguments @('-0p')
            if ($listing.ExitCode -eq 0) {
                foreach ($line in ($listing.StdOut -split [Environment]::NewLine)) {
                    if ($line -match '^\s*-V:(?<tag>\S+)(?:\s+\*)?\s+(?<path>.+?python\.exe)\s*$') {
                        [void]$candidatePaths.Add($Matches['path'].Trim())
                    }
                }
            } else {
                Write-Host 'Python launcher could not list interpreters; checking standard install paths instead.' -ForegroundColor Yellow
            }
        } catch {
            Write-Host "Python launcher listing was unavailable: $($_.Exception.Message)" -ForegroundColor Yellow
        }
    }

    # Fallback for python.org installs where the launcher is not present or
    # its listing does not include the executable.
    foreach ($minor in 15..10) {
        $directoryName = 'Python3' + $minor
        [void]$candidatePaths.Add((Join-Path $env:LOCALAPPDATA ('Programs\Python\' + $directoryName + '\python.exe')))
        [void]$candidatePaths.Add((Join-Path $env:ProgramFiles ($directoryName + '\python.exe')))
        [void]$candidatePaths.Add(('C:\' + $directoryName + '\python.exe'))
    }
    $pythonCommand = Get-Command 'python.exe' -ErrorAction SilentlyContinue
    if ($pythonCommand) { [void]$candidatePaths.Add($pythonCommand.Source) }

    $seen = @{}
    $validCandidates = New-Object System.Collections.ArrayList
    foreach ($candidate in $candidatePaths) {
        if (-not $candidate) { continue }
        try { $fullPath = [IO.Path]::GetFullPath($candidate) } catch { continue }
        if ($seen.ContainsKey($fullPath)) { continue }
        $seen[$fullPath] = $true
        if (-not (Test-SupportedPython $fullPath)) { continue }
        $versionResult = Invoke-CapturedProcess -FilePath $fullPath -Arguments @('-c', 'import sys; print(".".join(map(str,sys.version_info[:3])))')
        if ($versionResult.ExitCode -ne 0) { continue }
        try {
            $runtimeVersion = [version]$versionResult.StdOut.Trim()
            [void]$validCandidates.Add([pscustomobject]@{ Path = $fullPath; RuntimeVersion = $runtimeVersion })
        } catch { continue }
    }

    $selected = $validCandidates | Sort-Object -Property RuntimeVersion -Descending | Select-Object -First 1
    if ($selected) {
        return [pscustomobject]@{
            File = $selected.Path
            Prefix = @()
            Executable = $selected.Path
            Version = $selected.RuntimeVersion.ToString(2)
        }
    }
    return $null
}

function Write-ProcessOutput($Result) {
    if ($Result.StdOut) { Write-Host $Result.StdOut.TrimEnd() }
    if ($Result.StdErr) { Write-Host $Result.StdErr.TrimEnd() -ForegroundColor DarkGray }
}

function Invoke-SetupCommand([string]$FilePath, [string[]]$Arguments, [string]$FailureMessage) {
    $result = Invoke-CapturedProcess -FilePath $FilePath -Arguments $Arguments
    Write-ProcessOutput $result
    if ($result.ExitCode -ne 0) {
        throw "$FailureMessage (exit code $($result.ExitCode)). $($result.StdErr.Trim())"
    }
    return $result
}
function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $current = $env:Path
    $env:Path = (@($machine, $user, $current) | Where-Object { $_ }) -join ';'
}

Write-Host ''
Write-Host 'ScarClipScheduler 2.0.7 — installation checks' -ForegroundColor Cyan
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
            Start-Process 'https://apps.microsoft.com/detail/9NBLGGH4NNS1'
            throw 'No compatible 64-bit Python 3.10+ runtime was found and WinGet is unavailable. Windows App Installer is required for automatic Python setup. Install/update App Installer, then rerun ScarClipScheduler Setup.'
        }

        Write-Host 'No compatible Python 3.10+ runtime was found. Downloading and installing Python 3.14 for the current Windows user...' -ForegroundColor Yellow
        $wingetArgs = @(
            'install', '--id', 'Python.Python.3.14', '--exact', '--source', 'winget',
            '--scope', 'user', '--accept-package-agreements', '--accept-source-agreements'
        )
        Invoke-SetupCommand -FilePath $winget.Source -Arguments $wingetArgs -FailureMessage 'WinGet could not install Python 3.14.' | Out-Null
        Refresh-ProcessPath
        $python = Get-PythonCommand
        if (-not $python) {
            $knownPython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'
            if (Test-SupportedPython $knownPython) {
                $versionResult = Invoke-CapturedProcess -FilePath $knownPython -Arguments @('-c', 'import sys; print(".".join(map(str,sys.version_info[:2])))')
                $python = [pscustomobject]@{
                    File = $knownPython
                    Prefix = @()
                    Executable = $knownPython
                    Version = $versionResult.StdOut.Trim()
                }
            }
        }
        if (-not $python) {
            throw 'WinGet reported Python 3.14 installation complete, but no compatible Python executable could be found. Check installer-setup.log and rerun setup.'
        }
    }

    Write-Host "Using Python $($python.Version): $($python.Executable)" -ForegroundColor Green
    Write-Host 'Creating the isolated publishing-worker environment...' -ForegroundColor Gray
    $venvArgs = @('-m', 'venv', (Join-Path $install '.venv'))
    Invoke-SetupCommand -FilePath $python.File -Arguments $venvArgs -FailureMessage 'Could not create the isolated Python environment.' | Out-Null
    if (-not (Test-Path $pythonVenv)) {
        throw 'Python returned success, but the isolated environment executable was not created.'
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
    $healthCheck = Invoke-CapturedProcess -FilePath $pythonVenv -Arguments @('-m', 'pip', 'check')
    if ($healthCheck.ExitCode -eq 0) {
        $importCheck = Invoke-CapturedProcess -FilePath $pythonVenv -Arguments @('-c', 'import requests, googleapiclient, google.auth, google_auth_oauthlib, google_auth_httplib2, tzdata')
        if ($importCheck.ExitCode -eq 0) {
            $dependenciesReady = $true
        }
    }
}

if ($dependenciesReady) {
    Write-Host 'Required Python packages are already installed and healthy. Skipping package installation.' -ForegroundColor Green
} else {
    Write-Host 'Installing or repairing publishing-worker dependencies...' -ForegroundColor Yellow
    Invoke-SetupCommand -FilePath $pythonVenv -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', '--upgrade', 'pip') -FailureMessage 'Could not update pip.' | Out-Null
    Invoke-SetupCommand -FilePath $pythonVenv -Arguments @('-m', 'pip', 'install', '--disable-pip-version-check', '--prefer-binary', '-r', $requirements) -FailureMessage 'Could not install the publishing-worker dependencies.' | Out-Null
    Invoke-SetupCommand -FilePath $pythonVenv -Arguments @('-m', 'pip', 'check') -FailureMessage 'The installed Python dependencies are inconsistent.' | Out-Null
    Invoke-SetupCommand -FilePath $pythonVenv -Arguments @('-c', 'import requests, googleapiclient, google.auth, google_auth_oauthlib, google_auth_httplib2, tzdata') -FailureMessage 'A required publishing dependency could not be imported after installation.' | Out-Null
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
