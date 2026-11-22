$ErrorActionPreference = 'Stop'

$source = Split-Path -Parent $MyInvocation.MyCommand.Path
$localPrograms = Join-Path $env:LOCALAPPDATA 'Programs'
$install = Join-Path $localPrograms 'ScarClipScheduler'
$dataDir = Join-Path $env:LOCALAPPDATA 'ScarClipScheduler'
$pythonVenv = Join-Path $install '.venv\Scripts\python.exe'
$requirements = Join-Path $install 'backend\requirements.txt'
$exe = Join-Path $install 'ScarClipScheduler.exe'

Write-Host ''
Write-Host 'ScarClipScheduler 2.0.2 - Windows setup' -ForegroundColor Cyan
Write-Host 'Native WPF interface with a separate local publishing worker.' -ForegroundColor Gray
Write-Host ''

$existing = Get-Process -Name 'ScarClipScheduler' -ErrorAction SilentlyContinue
if ($existing) {
    throw 'ScarClipScheduler is already running. Use Quit in the app, then run this setup again.'
}

if (-not (Test-Path (Join-Path $source 'ScarClipScheduler.exe'))) {
    throw 'ScarClipScheduler.exe was not found beside this setup script. Extract the full Windows ZIP before running setup.'
}
if (-not (Test-Path (Join-Path $source 'backend\backend_service.py'))) {
    throw 'The backend folder is missing. Re-download the complete ScarClipScheduler Windows ZIP.'
}

New-Item -ItemType Directory -Force -Path $install | Out-Null

# Update only application files. The queue, settings and credentials live elsewhere.
$sourceFull = [IO.Path]::GetFullPath($source).TrimEnd('\\')
$installFull = [IO.Path]::GetFullPath($install).TrimEnd('\\')
if (-not [string]::Equals($sourceFull, $installFull, [StringComparison]::OrdinalIgnoreCase)) {
    Copy-Item -LiteralPath (Join-Path $source 'ScarClipScheduler.exe') -Destination $exe -Force
    $targetBackend = Join-Path $install 'backend'
    if (Test-Path $targetBackend) {
        Remove-Item -LiteralPath $targetBackend -Recurse -Force
    }
    Copy-Item -LiteralPath (Join-Path $source 'backend') -Destination $targetBackend -Recurse -Force
}

# Reuse an existing app environment if it is valid; otherwise create one.
if (Test-Path $pythonVenv) {
    & $pythonVenv -c "import sys; assert sys.version_info >= (3, 11)"
    if ($LASTEXITCODE -ne 0) {
        Remove-Item -LiteralPath (Join-Path $install '.venv') -Recurse -Force
    }
}

if (-not (Test-Path $pythonVenv)) {
    $python = $null

    $pyLauncher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & $pyLauncher.Source -3 -c "import sys; assert sys.version_info >= (3, 11)"
        if ($LASTEXITCODE -eq 0) {
            $python = (& $pyLauncher.Source -3 -c "import sys; print(sys.executable)").Trim()
        }
    }

    if (-not $python) {
        $pythonCommand = Get-Command 'python.exe' -ErrorAction SilentlyContinue
        if ($pythonCommand) {
            & $pythonCommand.Source -c "import sys; assert sys.version_info >= (3, 11)"
            if ($LASTEXITCODE -eq 0) {
                $python = $pythonCommand.Source
            }
        }
    }

    if (-not $python) {
        $winget = Get-Command 'winget.exe' -ErrorAction SilentlyContinue
        if (-not $winget) {
            Start-Process 'https://www.python.org/downloads/windows/'
            throw 'Python 3.11+ was not found and WinGet is unavailable. Install Python 3.12, reopen PowerShell, and run this setup again.'
        }

        Write-Host 'Installing Python 3.12 for the current Windows user...' -ForegroundColor Yellow
        & $winget.Source install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements
        if ($LASTEXITCODE -ne 0) {
            throw "WinGet could not install Python 3.12 (exit code $LASTEXITCODE)."
        }

        $pyLauncher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
        if ($pyLauncher) {
            $python = (& $pyLauncher.Source -3.12 -c "import sys; print(sys.executable)").Trim()
        }
        if (-not $python) {
            $knownPython = Join-Path $env:LOCALAPPDATA 'Programs\\Python\\Python312\\python.exe'
            if (Test-Path $knownPython) { $python = $knownPython }
        }
        if (-not $python) {
            throw 'Python installation completed but the Python executable was not found. Reopen PowerShell and run this setup again.'
        }
    }

    Write-Host "Creating the isolated Python environment with $python" -ForegroundColor Gray
    & $python -m venv (Join-Path $install '.venv')
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not create the application Python environment.'
    }
}

Write-Host 'Installing publishing-worker dependencies...' -ForegroundColor Gray
& $pythonVenv -m pip install --disable-pip-version-check --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'Could not update pip.' }
& $pythonVenv -m pip install --disable-pip-version-check -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'Could not install the publishing-worker dependencies.' }

# Keep the app data directory explicit; the worker defaults to this same path.
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

# Create a Start Menu shortcut for the native app.
$startMenu = [Environment]::GetFolderPath('Programs')
$shortcutPath = Join-Path $startMenu 'ScarClipScheduler.lnk'
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = $install
$shortcut.Description = 'ScarClipScheduler - YouTube Shorts and Facebook Page Reels'
$shortcut.Save()

Write-Host ''
Write-Host 'Setup complete.' -ForegroundColor Green
Write-Host "Application: $exe"
Write-Host "User data:   $dataDir"
Write-Host 'Your existing queue database, platform tokens, settings and scheduled-post records are stored separately and have not been removed.' -ForegroundColor Gray
Write-Host ''
$startNow = Read-Host 'Start ScarClipScheduler now? (Y/N)'
if ($startNow -match '^(y|yes)$') {
    Start-Process -FilePath $exe -WorkingDirectory $install
}
