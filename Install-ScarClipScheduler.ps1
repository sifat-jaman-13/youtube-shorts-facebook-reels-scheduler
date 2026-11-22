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

function Invoke-SetupCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )

    # Capture setup output in the transcript and stop on a non-zero exit code.
    $result = Invoke-CapturedProcess -FilePath $FilePath -Arguments $Arguments

    if (-not [string]::IsNullOrWhiteSpace($result.StdOut)) {
        Write-Host ($result.StdOut.TrimEnd())
    }
    if (-not [string]::IsNullOrWhiteSpace($result.StdErr)) {
        Write-Host ($result.StdErr.TrimEnd()) -ForegroundColor DarkYellow
    }

    if ($result.ExitCode -ne 0) {
        $details = @($result.StdErr, $result.StdOut) |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        $message = "$FailureMessage (exit code $($result.ExitCode))."
        if ($details.Count -gt 0) {
            $message += [Environment]::NewLine + ($details -join [Environment]::NewLine)
        }
        throw $message
    }

    return $result
}

function Test-SupportedPython([string]$Python) {
    if (-not $Python) { return $false }
    # Validate the interpreter resolved by the active Windows PATH command.
    # CPython 3.10+ (64-bit) is supported; there is no upper version limit.
    $checkCode = 'import sys; raise SystemExit(0 if sys.implementation.name == "cpython" and sys.version_info >= (3,10) and sys.version_info.releaselevel == "final" and sys.maxsize > 2**32 else 2)'
    try {
        $result = Invoke-CapturedProcess -FilePath $Python -Arguments @('-c', $checkCode)
        return ($result.ExitCode -eq 0)
    } catch { return $false }
}

function Get-PythonCommand {
    $pythonCommand = Get-Command 'python' -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        Write-Host 'python --version: command not found on PATH.' -ForegroundColor Yellow
        return $null
    }

    $pythonExe = $pythonCommand.Source
    try {
        $versionCheck = Invoke-CapturedProcess -FilePath $pythonExe -Arguments @('--version')
    } catch {
        Write-Host "python --version could not run: $($_.Exception.Message)" -ForegroundColor Yellow
        return $null
    }
    $versionText = ($versionCheck.StdOut + $versionCheck.StdErr).Trim()
    Write-Host "python --version -> $versionText" -ForegroundColor Gray
    if ($versionCheck.ExitCode -ne 0) { return $null }

    if (-not (Test-SupportedPython $pythonExe)) {
        Write-Host 'The Python command on PATH is not a supported 64-bit CPython 3.10+ installation.' -ForegroundColor Yellow
        return $null
    }

    $details = Invoke-CapturedProcess -FilePath $pythonExe -Arguments @('-c', 'import sys; print(".".join(map(str,sys.version_info[:3]))); print(sys.executable)')
    if ($details.ExitCode -ne 0) { return $null }
    $lines = @($details.StdOut -split [Environment]::NewLine | Where-Object { $_.Trim() })
    if ($lines.Count -lt 2) { return $null }
    Write-Host "Using interpreter from PATH: $($lines[1].Trim())" -ForegroundColor Gray
    return [pscustomobject]@{
        File = $pythonExe
        Prefix = @()
        Executable = $lines[1].Trim()
        Version = $lines[0].Trim()
    }
}
function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $current = $env:Path
    $env:Path = (@($machine, $user, $current) | Where-Object { $_ }) -join ';'
}

Write-Host ''
Write-Host 'ScarClipScheduler 2.0.11 - installation checks' -ForegroundColor Cyan
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
# outside supported 64-bit CPython 3.10+.
if (Test-Path $pythonVenv) {
    if (-not (Test-SupportedPython $pythonVenv)) {
        Write-Host 'The existing worker runtime is not a supported 64-bit CPython 3.10+ environment. Recreating it...' -ForegroundColor Yellow
        Remove-Item -LiteralPath (Join-Path $install '.venv') -Recurse -Force
    }
}

if (-not (Test-Path $pythonVenv)) {
    $python = Get-PythonCommand
    if (-not $python) {
        Write-Host 'No compatible python command was found on PATH. Starting automatic Python installation...' -ForegroundColor Yellow
        $winget = Get-Command 'winget' -ErrorAction SilentlyContinue

        if ($winget) {
            Write-Host 'Trying WinGet first: Python.Python.3.14...' -ForegroundColor Gray
            $wingetArgs = @(
                'install', '--id', 'Python.Python.3.14', '--exact', '--source', 'winget',
                '--scope', 'user', '--accept-package-agreements', '--accept-source-agreements'
            )
            try {
                Invoke-SetupCommand -FilePath $winget.Source -Arguments $wingetArgs -FailureMessage 'WinGet could not install Python 3.14.' | Out-Null
                Refresh-ProcessPath
                $python = Get-PythonCommand
            } catch {
                Write-Host "WinGet installation did not complete: $($_.Exception.Message)" -ForegroundColor Yellow
            }
        } else {
            Write-Host 'WinGet is not available. Falling back to the official Python.org installer...' -ForegroundColor Yellow
        }

        if (-not $python) {
            # Discover the newest stable 64-bit CPython installer from the
            # official Python downloads page. No user's Python install path
            # or fixed Python patch version is assumed.
            $previousProgressPreference = $ProgressPreference
            $ProgressPreference = 'SilentlyContinue'
            $pythonInstallerPath = $null
            try {
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                $downloadsPage = Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/downloads/windows/'
                $releaseMatches = [regex]::Matches(
                    $downloadsPage.Content,
                    'https://www\.python\.org/ftp/python/(?<version>3\.\d+\.\d+)/python-[^""''\s]+-amd64\.exe',
                    [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
                )
                $latestInstaller = $null
                foreach ($match in $releaseMatches) {
                    try {
                        $candidateVersion = [version]$match.Groups['version'].Value
                        if ($candidateVersion -ge [version]'3.10.0' -and
                            (-not $latestInstaller -or $candidateVersion -gt $latestInstaller.Version)) {
                            $latestInstaller = [pscustomobject]@{
                                Version = $candidateVersion
                                Url = $match.Value
                            }
                        }
                    } catch { }
                }
                if (-not $latestInstaller) {
                    throw 'The official Python downloads page did not expose a stable 64-bit installer for Python 3.10 or newer.'
                }

                $pythonInstallerPath = Join-Path $env:TEMP ("python-" + $latestInstaller.Version + "-amd64.exe")
                Write-Host "Downloading official CPython $($latestInstaller.Version) for Windows x64..." -ForegroundColor Gray
                Invoke-WebRequest -UseBasicParsing -Uri $latestInstaller.Url -OutFile $pythonInstallerPath

                $signature = Get-AuthenticodeSignature -LiteralPath $pythonInstallerPath
                if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid -or
                    $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
                    throw 'The downloaded Python installer did not pass the Python Software Foundation digital-signature check.'
                }

                Write-Host 'Installing Python for the current Windows user and adding it to PATH...' -ForegroundColor Gray
                $pythonInstall = Start-Process -FilePath $pythonInstallerPath -ArgumentList '/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=0 Include_test=0' -Wait -PassThru
                if ($pythonInstall.ExitCode -ne 0) {
                    throw "The official Python installer exited with code $($pythonInstall.ExitCode)."
                }
            } finally {
                $ProgressPreference = $previousProgressPreference
                if ($pythonInstallerPath -and (Test-Path $pythonInstallerPath)) {
                    Remove-Item -LiteralPath $pythonInstallerPath -Force -ErrorAction SilentlyContinue
                }
            }

            Refresh-ProcessPath
            $python = Get-PythonCommand
        }

        if (-not $python) {
            throw 'Python installation finished or was attempted, but the terminal still cannot resolve a compatible 64-bit CPython 3.10+ command. Check installer-setup.log for details.'
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
