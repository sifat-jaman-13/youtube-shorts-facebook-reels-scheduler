# Changelog

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
