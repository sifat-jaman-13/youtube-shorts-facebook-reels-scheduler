ScarClipScheduler 2.0.4 — Windows installer
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
WinGet is used to install Python 3.12 if no supported Python is found.

The app uses a self-contained .NET 10 WPF executable. You do not need to
install the .NET runtime separately. Python 3.11 or 3.12 (64-bit) is used by
the separate local publishing worker. The installer opens the setup terminal
so dependency checks and any automatic installation are visible.

UNINSTALL
---------
Open Start Menu → ScarClipScheduler → Uninstall ScarClipScheduler, or use
Windows Settings → Apps → Installed apps → ScarClipScheduler → Uninstall.
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
