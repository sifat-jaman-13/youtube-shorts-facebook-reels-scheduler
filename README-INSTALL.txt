ScarClipScheduler 2.0.16 â€” Windows installer
============================================

1. Download and run ScarClipScheduler-Setup.exe.
2. Follow the Windows installer. It places the self-contained native WPF app
   under:
       %LOCALAPPDATA%\Programs\ScarClipScheduler
3. During installation, a PowerShell setup window opens. This is intentional:
   it checks for a compatible Python runtime, creates the app's isolated
   Python environment, verifies the publishing-worker dependencies, and
   installs anything missing.
4. When setup finishes, answer Y in that window to launch ScarClipScheduler,
   or open it later from the Start Menu / desktop shortcut.

DEPENDENCY CHECK BEHAVIOUR
--------------------------
The dependency check runs during installation only. It is not run whenever
you open the app. If a compatible Python environment and matching packages
are already present and healthy, setup reuses them and skips package installs.
If Python or required packages are missing, setup attempts to install them.
The installer does not require a particular Python install folder or version-specific launcher. It uses the normal `python` command resolved from the current Windows PATH.
Setup checks `python --version` through the current Windows PATH. Any 64-bit CPython 3.10+ version is accepted, including Python 3.14 and newer. If the command is missing or unsupported, the visible setup terminal attempts WinGet first. If WinGet is unavailable or its installation fails, setup downloads the newest stable 64-bit installer from python.org, verifies its Python Software Foundation digital signature, installs Python for the current Windows user, refreshes PATH, and verifies `python --version` again.

The app uses a self-contained .NET 10 WPF executable. You do not need to
install the .NET runtime separately. 64-bit CPython 3.10 or newer is used by
the separate local publishing worker. The installer opens the setup terminal
so dependency checks and any automatic installation are visible. If a check
fails, Setup stops instead of reporting success. The terminal stays open until
you press Enter, and the full diagnostic transcript is saved to:
       %LOCALAPPDATA%\ScarClipScheduler\installer-setup.log

UNINSTALL
---------
Open Start Menu â†’ ScarClipScheduler â†’ Uninstall ScarClipScheduler, or use
Windows Settings â†’ Apps â†’ Installed apps â†’ ScarClipScheduler â†’ Uninstall.
The uninstaller removes the installed program files and shortcuts. It keeps
your user data under %LOCALAPPDATA%\ScarClipScheduler.

DATA SAFETY
-----------
Your queue database, scheduled-post IDs, settings, OAuth tokens, Meta
credentials, and logs remain under:
       %LOCALAPPDATA%\ScarClipScheduler

Updating the application replaces program files only. User data is stored
outside the application directory and is preserved. The installer refuses
to update or uninstall while ScarClipScheduler is running. Use Quit in the
app and allow active publishing work to finish before installing an update.

ScarClipScheduler uses your own Google YouTube Data API and Meta Graph API
authorization. Keep OAuth files, tokens, Meta App Secrets, and database
backups private.
