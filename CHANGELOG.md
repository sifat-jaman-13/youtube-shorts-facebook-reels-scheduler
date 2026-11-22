# Changelog

## [2.0.9] - 2026-11-22

### Fixed

- Styled native WPF category dropdown options with a dark background, readable light text, and distinct hover and selected states.
- Adjusted the native window to fit within the available Windows desktop work area and center on startup, allowing smaller displays to show the full interface more reliably.

## [2.0.8] - 2026-11-22

### Fixed

- Added the missing checked `Invoke-SetupCommand` helper used by the Windows installer to create the isolated Python environment and install or verify publishing-worker dependencies.
- Captures and displays command output in the setup transcript and stops installation with the exit code and diagnostic output when a command fails.
- Added regression coverage confirming the helper is defined before its first use.

## [2.0.7] - 2026-11-22

### Fixed

- Replaced version-specific Python launcher probing with the normal `python --version` command resolved from the current Windows PATH.
- Supports 64-bit CPython 3.10 and newer, without an upper version cap or hard-coded per-user Python installation paths.
- When the PATH command is missing or unsupported, the visible setup terminal tries WinGet first, then falls back to downloading the latest stable 64-bit installer from python.org, verifies its Python Software Foundation signature, installs for the current user, and repeats the PATH check.
- Keeps Python dependency checks and repairs inside the install-only setup process; normal app launches do not reinstall dependencies.

## [2.0.6] - 2026-11-22

### Fixed

- Fixed Python detection on Windows PowerShell 5.1: setup now reads the installed-interpreter list and validates executable paths directly instead of invoking a missing version such as `py -3.12` as a failing native command.
- Python 3.11 is selected correctly when Python 3.12 is not installed.
- Added a captured-process helper so optional runtime probes cannot abort the installer under `$ErrorActionPreference = 'Stop'`.

## [2.0.5] - 2026-11-22

### Fixed

- Replaced the unchecked PowerShell post-install command with a checked installer step; Setup now stops when prerequisite configuration exits with an error.
- Added a persistent setup transcript at `%LOCALAPPDATA%\\ScarClipScheduler\\installer-setup.log` and keeps the failed setup terminal open until the error has been read.
- Reworded the Finish page so it confirms success directly and tells users where to launch the app.
- Retained the Start Menu uninstaller shortcut introduced in 2.0.4.

## [2.0.4] - 2026-11-22

### Fixed

- Added an explicit **Uninstall ScarClipScheduler** shortcut to the Start Menu app group.
- Documented the uninstall path and clarified that uninstalling preserves the separate local user-data directory.

## [2.0.3] - 2026-11-22

### Changed

- Replaced the portable ZIP distribution with a standard single-file Windows setup executable.
- Added an Inno Setup installer that runs the PowerShell prerequisite check visibly during installation.
- The installer validates the existing Python 3.11 / 3.12 environment and dependency fingerprint, skips healthy matching installs, and installs or repairs missing / changed dependencies.
- Added a safe installer guard that refuses updates or uninstall while ScarClipScheduler is running, protecting active publishing work.
- Updated installation documentation, a navigable README contents section, and the single-banner README layout.

## [2.0.2] - 2026-11-22

### Changed

- Removed the Support Terminal button, automatic terminal launch, and terminal script. Normal operation is fully contained in the native WPF app; status and publishing events remain available in the Activity log.
- Simplified the About window: removed the connected Facebook Page list and the credential disclaimer. Creator credits, GitHub repositories, YouTube channels, and other public profile links remain.
- Updated the About and window version to 2.0.2.

## [2.0.1] - 2026-11-22

### Added

- Added an About window crediting Sifat Jaman / ScarZero and ChatGPT by OpenAI, linking the creator's GitHub projects, the connected YouTube channel and connected Facebook Pages.
- Added an automatically opened Support terminal that tails app and worker logs; the header button can reopen it, and closing it does not stop the app.
- Redacts common API keys, OAuth tokens and bearer credentials in the terminal display.

### Changed

- YouTube Reconnect now forces a fresh Google OAuth authorization and restores the previous valid token if the new authorization fails.
- Added clear Connecting/Reconnecting status text while platform authorization is in progress.
- Clarified that the Python publishing worker is hidden during normal operation; the WPF app and Activity log remain the primary interface.

### Preserved

- Closing the optional Support terminal does not stop the app.
- Disconnect removes local credentials only; already accepted platform-side schedules and queue history are preserved.

## [2.0.0] - 2026-11-22

### Changed

- Replaced the Python/Tkinter and Qt desktop windows with a native .NET 10 WPF Windows application.
- Separated the responsive WPF interface from the existing Python publishing service; YouTube and Meta API logic, OAuth tokens, queue database and file layout are retained.
- Added virtualized, incrementally updated clip-grid rows, separate action/status areas, readable schedule controls and ellipsized metadata cells with full-text tooltips.
- Added explicit YouTube and Facebook connection states with Reconnect and Disconnect actions.
- Disconnect removes the locally stored OAuth/Page tokens only. It does not cancel posts already accepted by YouTube or Facebook or delete queue history.

## [1.5.0] - 2026-11-22

### Changed

- Replaced the Tkinter desktop interface with a native Qt Widgets interface built with PySide6 Essentials.
- Kept the existing YouTube/Meta publishing engine, SQLite schema, local settings, OAuth tokens, and queue records in place.
- Routed worker-thread UI updates through Qt's queued signal mechanism; scanning, uploads, OAuth, and publication verification continue outside the UI thread.
- Added separate hour and minute interval controls (1 minute through 24 hours), plus a next-5:00-AM start preset. A blank first-run schedule defaults to the next 5:00 AM in Windows local time.
- Changed the Windows bootstrapper to install the Qt front end and launch qt_app.py.

### Preserved

- Existing accepted YouTube and Facebook schedules are not resubmitted by the UI migration.
- Existing queue database, Page tokens, Google OAuth token, settings, and clip files remain in the same local data folder.

## [1.4.0] - 2026-11-22

### Added

- Added an in-app MP4/TXT import guide with exact matching-name examples and missing-sidecar behaviour.
- Added a dedicated Quit button and a clear Windows terminal running-status banner.
- Added an explicit Stop queue action and explained its graceful stop behaviour.

### Changed

- Clarified multi-selection: Ctrl-click and Shift-click select a batch for scheduling; the metadata editor applies only to the first highlighted clip.
- The selection counter now distinguishes a single clip, a batch, and the full queue.
- Documented the precise same-basename MP4/TXT pairing rule in the README.
- Bumped the app and bootstrapper to version 1.4.0.

### Preserved

- Multi-select batch scheduling remains available.
- Already accepted platform schedules remain unchanged when the local queue is stopped.
- Existing queue data, settings, and OAuth credentials remain in the local user-data folder.

## [1.3.0] - 2026-11-22

### Changed

- Redesigned the desktop interface with a dark navy palette, violet/blue accents, clearer visual hierarchy, modern tab styling, and more readable tables and inputs.
- Added the ScarClipScheduler film/play/clock logo to the app header, window icon, taskbar, and Windows EXE.
- Bundled the logo PNG and multi-size ICO in the Windows bootstrapper and added them to package verification.
- Increased the default window size while retaining a practical resizable minimum.

### Preserved

- Publishing, OAuth, scheduling, upload, queue, and cleanup behavior remains unchanged.
- Existing local queue database, settings, and credentials remain in their current user-data folder.

## [1.2.0] - 2026-11-22

### Added

- Added a Delete from list action beside Select all. It removes selected local queue rows and Facebook Page job history while leaving the actual MP4/TXT files and platform-side schedules untouched.
- Added title and description columns for every detected clip, a single-row editor, double-click focus, and metadata saving per video.
- Added selection-aware scheduling: one selected row schedules one clip, Ctrl/Shift selection schedules a group, and an empty selection retains whole-queue scheduling.
- Added a Windows terminal bootstrapper EXE with the Python application and requirements embedded as resources. On first run it checks for Python 3.11+, attempts a per-user Python 3.12 install through winget if missing, creates an isolated virtual environment, installs pip dependencies, and launches the app.
- Added a modern SVG README banner, API credential setup tables, detailed EXE/setup instructions, and creator / ChatGPT attribution.
- Added a Windows GitHub Actions workflow to build and upload the terminal bootstrapper as a workflow artifact.

### Fixed

- Made selected-row restoration use full video paths, not just filenames, to avoid collisions between videos with the same basename.
- Prevented queue removals from racing with scanning, scheduling, or publication-verification workers.

## [1.1.9] - 2026-11-22

### Fixed
- Reassign missing or expired YouTube publish times when retrying pending/failed uploads.
- Preserve future publish times and never alter already accepted Scheduled or Published videos.
- Allocate retry slots after the existing future queue and enforce a maximum of 100 planned YouTube publication slots per Pacific calendar day.

### Added
- Offline regression tests for retry allocation, Pacific-day slot limits, TXT parsing, queue status aggregation, publication-confirmed cleanup, paired file moves, and rollback.
- Windows GitHub Actions regression workflow for Python 3.11 and 3.12.

## [1.1.8] - 2026-11-22

### Added
- Initial public repository release with YouTube Shorts and Facebook Page Reels scheduling, multi-Page status tracking, publication verification, and manual-review cleanup workflow.
