ScarClipScheduler 2.0.2 — Windows x64 setup
===========================================

1. Extract the complete ZIP file to a normal folder.
2. Right-click Install-ScarClipScheduler.ps1 and choose Run with PowerShell.
   Alternatively, open PowerShell in the extracted folder and run:
       powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-ScarClipScheduler.ps1
3. The setup installs the app files under:
       %LOCALAPPDATA%\Programs\ScarClipScheduler
   It prepares an isolated Python environment for the publishing worker,
   installs its dependencies, creates a Start Menu shortcut, and can launch
   the app when setup finishes.
4. Open ScarClipScheduler from the Start Menu or its installed EXE.

The desktop interface is a native .NET 10 WPF application and includes the
.NET runtime in its self-contained Windows build. Python 3.11+ is used only by
the separate local publishing worker. Setup uses WinGet to install Python
3.12 when a compatible Python installation is not found.

Your queue database, settings, OAuth tokens, Meta credentials, and logs remain
under:
       %LOCALAPPDATA%\ScarClipScheduler

Updating the app replaces application files only. It does not delete or reset
the user-data folder. Do not run two copies of ScarClipScheduler at once.
Use Quit inside the app to shut it down cleanly.

ScarClipScheduler uses official Google YouTube Data API and Meta Graph API
authorization. You must supply your own credentials in the app. Keep OAuth
files, tokens, Meta App Secrets, and local database backups private.
