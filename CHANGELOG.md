# Changelog

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
