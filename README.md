# ScarClipScheduler

<p align="center">
  <img src="assets/scarclipscheduler-banner.svg" alt="ScarClipScheduler — Schedule Shorts and Reels with control" width="100%">
</p>


<p align="center">
  <a href="https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler?display_name=tag&sort=semver"></a>
  <a href="https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler/releases/latest/download/ScarClipScheduler-Setup.exe"><img alt="Windows installer" src="https://img.shields.io/badge/download-Windows%20installer-2563eb?logo=windows"></a>
  <a href="https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler/actions/workflows/build-exe.yml"><img alt="Windows build" src="https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler/actions/workflows/build-exe.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="Custom Non-Commercial Licence" src="https://img.shields.io/badge/license-custom--non--commercial-orange"></a>
</p>

**Version 2.0.18 — Native Windows WPF desktop scheduler**

[Website](https://sifat-jaman-13.github.io/youtube-shorts-facebook-reels-scheduler/) · [GitHub repository](https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler) · [Latest release](https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler/releases/latest)

ScarClipScheduler is a native Windows desktop app for preparing and scheduling short-form videos to YouTube Shorts and Facebook Page Reels. It watches a folder of MP4 clips and optional matching TXT metadata, lets you choose destinations and publish times, and sends uploads through the official Google and Meta APIs.

## Navigation

- [Overview and features](#what-this-build-uses)
- [Desktop app and background worker](#desktop-application-and-background-worker)
- [Scheduling workflow](#scheduling-workflow)
- [Platform connections](#connections)
  - [YouTube](#youtube)
  - [Facebook Page Reels](#facebook-page-reels)
- [Clip folder and TXT metadata](#clip-folder-and-txt-format)
- [Queue statuses and file handling](#queue-statuses-and-file-handling)
- [Installation requirements](#before-you-install-windows)
- [Install on Windows](#install-and-run)
  - [New installation](#new-windows-installation-recommended)
  - [Existing installation / update](#existing-windows-installation)
  - [Run from source](#run-from-source)
  - [Build the installer](#build-the-windows-installer)
- [Uninstall](#uninstall)
- [Data and security](#data-and-security)
- [Tests](#tests)
- [Project credits](#project-credits)
- [License](#license)
- [Changelog](CHANGELOG.md)

## What this build uses

- **Native Windows interface:** built with .NET 10 and WPF. The desktop UI does not use Tkinter, Qt, or an embedded browser.
- **Background publishing worker:** the Python engine runs as a separate hidden process, keeping the desktop interface responsive during scans, uploads, scheduling, and verification.
- **Responsive queue:** the clip table uses row and column virtualization with incremental updates rather than rebuilding the entire list after every change.
- **No console window during normal use:** monitor progress, status changes, and errors in the built-in Activity log and status footer.
- **Local-only communication:** the WPF app talks to its worker over `127.0.0.1` on a dynamically selected port, protected by a fresh random token for each launch.
- **Unified destination view:** manage YouTube and Facebook results in one queue, with separate status tracking for each Facebook Page.
- **Account management:** view connection status and reconnect or disconnect accounts from the Connections page.
- **Flexible selection:** schedule one clip, several selected clips, or the entire queue.
- **Metadata editor:** review and update each clip's title and description before publishing.
- **Schedule controls:** set the first post date and time, then choose an interval in hours and minutes. Past dates and start times that are too close or already passed are rejected.
- **Separate Scheduled screen and dedicated Scheduled view:** clips move out of Detected after all destinations selected for that run accept them. The Scheduled view keeps their platform IDs and accepted publish times.
- **Manual cleanup folder:** once every selected destination accepts the full upload and returns an external ID, the MP4/TXT pair is moved out of the watched folder into `You can delete this`. The **SAFE TO DELETE** button opens that folder; the app never permanently deletes the files.
- **Protected history clearing:** clear visible Scheduled rows only after the app creates and verifies a SQLite backup. Permanent upload receipts and SHA-256 duplicate protection remain intact.
- **Safe queue removal:** remove local queue entries without cancelling posts that a platform has already accepted.
- **Publication checks:** query the platforms after the scheduled time and mark posts Published only when their status can be verified.
- **About page and credits:** view project credits and links to the creator's public GitHub projects and channels.

## Desktop application and background worker

The desktop app is a native WPF executable. When it starts, it launches the Python publishing worker as a separate background process without showing a console window. The worker listens only on `127.0.0.1` and chooses an available local port; requests from the desktop app are authenticated with a per-launch random token.

The status footer shows the worker and queue state. Open **Activity log** to review scanning, upload, scheduling, verification, and error messages. You do not need to open or keep a separate terminal running during normal use.

Close the app with **Quit**. When a scan, upload, or verification is active, ScarClipScheduler asks before closing and attempts to let the current operation finish. A long-running operation may trigger a second prompt before forced shutdown. Avoid ending the worker from Task Manager while a platform request is in progress.

## Scheduling workflow

1. Choose the folder that contains your MP4 clips and their matching TXT metadata files.
2. Select **Scan clips** and review the files detected in that folder.
3. Select the clips you want to publish. Leave the selection empty to use the full queue.
4. Select a clip to review or edit its title and description, then save any changes.
5. Open **Connections** and authorize your YouTube channel, Facebook account, or both.
6. When using Facebook, choose the Pages that should receive the Reels.
7. Set the first publish date and time, then choose the interval between posts. The supported interval is **5 minutes to 24 hours**.
8. Select **Confirm start time** to save and confirm the schedule. Changing the date, time, or interval clears that confirmation, so confirm again before starting.
9. Choose YouTube Shorts, Facebook Page Reels, or both. Confirm that you own the videos or have permission to publish them, select **Schedule queue**, and approve the final summary.

ScarClipScheduler uploads the selected videos when you start the queue and asks each selected platform to publish them at the times you chose. A destination is marked **Scheduled** only after its API accepts the full upload and returns an external video or Reel ID. This confirms that the platform accepted the scheduled post; it does **not** mean the post is already public.

When every destination selected for a clip has accepted it, the app moves the MP4 and matching TXT file out of the watched folder into `You can delete this`. The clip then leaves **Detected** and remains visible in the **Scheduled** view with its platform IDs and accepted publish times. The platform has the scheduled upload, so the local copies are no longer needed for that accepted post. You can delete those local copies manually when you are ready.

The first clip that still needs uploading uses the confirmed start time; subsequent clips are spaced by the chosen interval. Scanning does not silently change your selected start time. The first publish time must be at least **15 minutes in the future** when you start the queue.

YouTube's daily upload quota can pause the remaining YouTube jobs and move their unaccepted publish slots into the next available quota window. Facebook Page uploads are processed sequentially. The app does not impose its own daily cap; it continues until Meta returns an API rejection. A definite rejection marks that Page's job **Failed** and moves its retry slot forward by approximately one day plus a 15-minute buffer. Use **Reset failed** and start the queue again when you are ready to retry it.

A timeout or other ambiguous network result is marked **Partial** and locked against automatic re-upload because the platform may already have received the video. Check YouTube Studio or Meta Business Suite before taking further action. Jobs already accepted by a platform are never submitted again automatically.

Use the native app's **How to use** page for an in-app guide to MP4/TXT naming, clip detection, the Detected-to-Scheduled workflow, the cleanup folder, and **Clear history**. The green **SAFE TO DELETE** button opens the selected source folder's `You can delete this` subfolder in File Explorer.

### Upload history and duplicate protection (SQLite)

ScarClipScheduler stores its local queue and publishing history in SQLite at:

~~~text
%LOCALAPPDATA%\ScarClipScheduler\queue.db
~~~

Since version 2.0.15, the database includes a permanent upload ledger. Each ledger entry is identified by this composite primary key:

~~~sql
PRIMARY KEY (video_name, scheduled_at, platform, destination_id)
~~~

`platform` identifies YouTube or Facebook, while `destination_id` identifies the YouTube channel or the Facebook Page. Each receipt records the upload status, external video or session ID, attempt count, timestamps, and most recent error.

Every MP4 is fingerprinted with SHA-256. A database-level unique index prevents identical video content from being claimed again for the same platform destination, even if its filename, folder, or scheduled time changes. Each Facebook Page and the connected YouTube channel is treated as a separate destination, with its own upload receipt.

Before a network upload begins, the worker atomically claims the corresponding ledger entry and marks it **Uploading**. For Facebook, it saves the session ID after the START request, records **Uploaded** after the video bytes are transferred, and records **Scheduled** only after Meta accepts the FINISH request. For YouTube, the job becomes **Scheduled** when the upload API returns a video ID.

A clear platform rejection is recorded as **Failed**. **Reset failed** makes those confirmed failures eligible for another attempt. An interrupted or ambiguous request is recorded as **Partial**; a Facebook job whose binary transfer completed but whose final scheduling response is missing remains **Uploaded**. These states are deliberately excluded from **Reset failed**. Check YouTube Studio or Meta Business Suite before retrying an uncertain job—the lock is there to prevent an accidental duplicate upload.

On the first startup with version 2.0.15, the app creates a backup of the existing database in a neighbouring `backups` folder and imports known YouTube video IDs and Facebook Page Reel IDs into the ledger. Existing queue entries and per-Page history are retained.

## Connections

### YouTube

Connect YouTube with a Google Cloud OAuth 2.0 client configured as a **Desktop app**. Enable the YouTube Data API v3, configure the OAuth consent screen, create the Desktop app client, and choose its downloaded JSON file on the **Connections** page.

After connection, the app displays the channel name. **Reconnect YouTube** starts a new Google authorization flow. If reconnecting fails, the previous local token is restored. **Disconnect** removes the saved OAuth token and channel details from this PC; it does not cancel videos that YouTube has already accepted and scheduled.

### Facebook Page Reels

Create a Meta developer app and configure the Page permissions required by the publishing flow. Enter its Meta App ID, App Secret, and Business Portfolio ID on the **Connections** page, complete authorization in your browser, and select the Facebook Pages that should receive Reels.

The Connections page shows the Facebook connection state and how many Pages are available. **Reconnect Facebook** repeats the authorization flow. **Disconnect** removes the saved Page tokens and connection details from this PC, but it does not cancel Reels that Facebook has already accepted and scheduled.

For Facebook Reels, ScarClipScheduler builds one caption from the clip title, a blank line, and the full TXT description. It sends that complete string in both Meta's `title` and `description` fields. This keeps the title and caption aligned and avoids showing only a trailing part of the description—such as a creator credit or hashtags—as the Reel title.

Disconnecting is local to this installation. To revoke the app's permissions at the platform level, use the relevant Google or Facebook account settings.

## Clip folder and TXT format

Place MP4 files and their matching TXT files directly in the selected folder. Each pair must use the same filename (only the extension differs):

~~~text
clips/
  highlight_001.mp4
  highlight_001.txt
  highlight_002.mp4
  highlight_002.txt
~~~

The first non-empty line in the TXT file is used as the video title; all remaining lines form the description. TXT files are optional. Without one, the app uses the MP4 filename as the title and leaves the description empty. The scanner checks the selected folder only, not its subfolders.

## Queue statuses and file handling

- **Pending:** no upload has started for this destination.
- **Uploading:** the upload is in progress.
- **Partial:** the result is uncertain; the platform may have received the video, but the app did not receive a final confirmation. The job is locked against automatic re-upload.
- **Uploaded:** Facebook accepted the video-byte transfer, but the final scheduling request has not been confirmed. The job is locked against automatic re-upload.
- **Scheduled:** the platform accepted the upload and its scheduled publish request.
- **Published:** the app verified publication through the platform API.
- **Failed:** the platform explicitly rejected the request, or a local check prevented the upload. Review the Activity log and use **Reset failed** when you are ready to retry a confirmed failure.
- **Skipped:** the destination was intentionally bypassed, for example because the clip failed the Facebook Reel format check.

The overall row is shown as **Partial** when the selected destinations have mixed results. The YouTube and Facebook columns continue to show the individual status for each platform.

The **Detected** view contains clips that still need action for at least one destination in the current publishing scope. Once every selected destination accepts a clip, it leaves Detected automatically.

The **Scheduled** view contains clips accepted by every destination selected for that upload, with an external video or Reel ID returned by each platform. It shows the accepted publish time for each destination. **Scheduled does not mean Published**: the platform has accepted the video and future publication request, but the post may not be public yet.

As soon as every selected destination accepts the full upload and returns its external ID, the app moves the MP4 and matching TXT out of the scanned folder into `You can delete this`. This prevents the same local files from being picked up by a later scan. Use **SAFE TO DELETE** to open the folder. It is a manual cleanup area: ScarClipScheduler never permanently deletes your videos or TXT files. You decide when to remove the local copies. Checking the platform's scheduled-content list is useful, but it does not control when the files are moved.

If any destination in the selected publishing scope is still Pending, Failed, Partial, or otherwise unresolved, the clip remains in Detected and its local files stay in the source folder. The app moves the files only after every selected destination has accepted the upload.

**Clear history** removes the visible rows from the Scheduled screen only after creating and verifying a SQLite backup. It does not cancel posts on YouTube or Meta, delete files from `You can delete this`, or erase the permanent `upload_ledger`. Platform IDs and SHA-256 fingerprints remain in the ledger, so clearing the screen does not make an already accepted video eligible for another upload.

**Delete from list** removes the selected active queue records and their per-Page job rows from the local database. It leaves the MP4/TXT files untouched and does not cancel any post already accepted by YouTube or Meta.

## Before you install (Windows)

Use this checklist to prepare your Windows PC. **The installer still performs its own checks.** When you run ScarClipScheduler-Setup.exe, its visible PowerShell window validates the required Python runtime and installs missing prerequisites when possible.

### Requirements for normal installation

- **Operating system:** Windows 10 or Windows 11 (64-bit/x64).
- **Python:** 64-bit **CPython 3.10 or later** for the local publishing worker. Setup checks the `python` command on the Windows PATH. The current CI matrix tests Python 3.10, 3.11, 3.12, 3.14, and 3.15. If no supported interpreter is found, setup attempts to install Python 3.14 through WinGet.
- **WinGet / App Installer:** the preferred automatic installer when Python is missing. If WinGet is unavailable or cannot install Python, setup downloads the latest stable 64-bit CPython installer from python.org, verifies its digital signature, and installs it for the current user.
- **Internet connection:** required to install Python packages during setup and to communicate with Google and Meta while using the app.
- **PowerShell:** included with Windows; the installer uses a visible PowerShell window to show prerequisite checks and installation output.
- **.NET:** no separate .NET runtime installation is required for the published app; the WPF executable is self-contained.
- **FFmpeg:** not required by ScarClipScheduler.

### Official downloads

| Requirement | Download |
|---|---|
| Python 3.10+ for Windows (64-bit) | [python.org — Windows downloads](https://www.python.org/downloads/windows/) |
| WinGet / App Installer | [Microsoft Store — App Installer](https://apps.microsoft.com/detail/9NBLGGH4NNS1) |
| Git (source checkout only) | [git-scm.com — Windows](https://git-scm.com/download/win) |
| .NET 10 SDK (developers building from source only) | [Microsoft — .NET 10 downloads](https://dotnet.microsoft.com/en-us/download/dotnet/10.0) |
| Inno Setup 6 (developers building the installer only) | [Inno Setup official download](https://jrsoftware.org/isdl.php) |

### Check / prepare Python before installation (optional)

These checks are optional. The installer performs the same validation automatically. When `python --version` reports a supported 64-bit CPython 3.10+ installation, you do not need to install Python manually.

~~~powershell
# Check the same command the installer checks
python --version

# Verify this is 64-bit CPython 3.10+
python -c "import sys; print(sys.executable); print(sys.implementation.name); print(sys.maxsize > 2**32); assert sys.implementation.name == 'cpython' and sys.version_info >= (3, 10) and sys.maxsize > 2**32"

# Check WinGet (used only if no compatible Python command is available)
winget --version
~~~

If the `python` command is missing or points to an unsupported runtime, setup first attempts to install Python 3.14 with WinGet. If WinGet is unavailable or the installation fails, setup downloads the latest stable 64-bit installer from python.org, verifies the Python Software Foundation digital signature, installs Python for the current user, refreshes PATH, and checks the interpreter again.

### Extra requirements for developers building from source

These tools are **not required** to install or run the released setup EXE. Install them only if you plan to clone the repository, build the WPF application, or compile the Windows installer yourself.

~~~powershell
# Optional developer tools
winget install --id Git.Git --exact --source winget --accept-package-agreements --accept-source-agreements
winget install --id Microsoft.DotNet.SDK.10 --exact --source winget --accept-package-agreements --accept-source-agreements
winget install --id JRSoftware.InnoSetup --exact --source winget --accept-package-agreements --accept-source-agreements

# Verify developer tools
git --version
dotnet --info
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /?
~~~

### What the installer checks automatically

When you run **ScarClipScheduler-Setup.exe**, a visible PowerShell window performs the following steps:

1. runs `python --version` using the command resolved from the current Windows PATH, then validates that it is 64-bit CPython 3.10 or newer;
2. attempts to install Python automatically if the PATH command is missing or unsupported: WinGet first, then the official signed python.org installer if WinGet is unavailable or fails; it repeats the `python --version` check after installation;
3. creates or validates the app's isolated .venv;
4. checks the installed dependency set against the packaged requirements.txt;
5. installs or repairs packages only when the environment is new, incomplete, unhealthy, or the requirements have changed;
6. asks whether to launch ScarClipScheduler when setup is complete.

If prerequisite setup fails, installation stops instead of displaying a successful completion message. Diagnostics are written to `%LOCALAPPDATA%\ScarClipScheduler\installer-setup.log`, and the PowerShell window remains open so you can review the error.

The prerequisite process runs **during installation only**. Later launches start the WPF app and publishing worker; they do not reopen the setup window or reinstall Python packages.

## Install and run

### New Windows installation (recommended)

Download **ScarClipScheduler-Setup.exe** from the [latest GitHub release](https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler/releases/latest).

1. Double-click **ScarClipScheduler-Setup.exe**. Do not extract a ZIP.
2. Follow the normal Windows installer prompts.
3. During installation, the PowerShell setup window opens automatically. It checks the required Python runtime and publishing-worker packages, then attempts to install anything missing.
4. When the setup window asks **Start ScarClipScheduler now?**, choose **Y** to launch it immediately. You can also start it later from the Start Menu or optional desktop shortcut.

Setup displays its progress in PowerShell. If a compatible Python runtime and the required packages are already installed and healthy, it reuses the existing environment and skips package installation. This dependency check is not repeated every time you launch the desktop app.

The desktop executable is a self-contained .NET 10 WPF application; a separate .NET runtime installation is not required. The Python publishing worker runs in the background without a support-terminal window during normal app use.

### Existing Windows installation

The installed application and its private Python environment are stored under:

~~~text
%LOCALAPPDATA%\Programs\ScarClipScheduler\
~~~

Your queue database, scheduled-post IDs, settings, OAuth tokens, Meta credentials, and logs are stored separately under:

~~~text
%LOCALAPPDATA%\ScarClipScheduler\
~~~

Updating replaces the installed program files only. It preserves the separate user-data folder and does not cancel posts already accepted by YouTube or Facebook. Close ScarClipScheduler before running an update; the installer refuses to replace files while the app is running.

## Uninstall

Uninstall from **Start Menu → ScarClipScheduler → Uninstall ScarClipScheduler**, or from **Windows Settings → Apps → Installed apps → ScarClipScheduler → Uninstall**. The uninstaller removes the installed application and shortcuts but keeps your queue database, scheduled-post history, settings, OAuth tokens, Meta credentials, and logs in `%LOCALAPPDATA%\ScarClipScheduler`. A later reinstall can reuse that data.

### Run from source

Requirements:

- Windows 10/11 (64-bit/x64)
- .NET 10 SDK
- 64-bit CPython 3.10 or newer
- Internet access to install Python dependencies and communicate with the platform APIs

Clone the repository and use the included launcher. It checks the local developer prerequisites, creates the Python virtual environment, installs the worker dependencies when needed, and starts the WPF app:

~~~powershell
git clone https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler.git
cd youtube-shorts-facebook-reels-scheduler
.\Start ScarClipScheduler.bat
~~~

Or create the environment and launch the project manually:

~~~powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
dotnet run --project .\native\ScarClipScheduler.Wpf\ScarClipScheduler.Wpf.csproj
~~~

### Build the Windows installer

Build on Windows with the .NET 10 SDK and Inno Setup 6 installed:

~~~powershell
.\build_windows_exe.ps1
~~~

The build outputs **dist/installer/ScarClipScheduler-Setup.exe**. The installer contains the self-contained WPF application, Python publishing worker, dependency list, required assets, and first-install PowerShell setup script. It does not include account credentials, queue data, or user settings.


## Data and security

The app stores its local queue database, settings, logs, and account tokens under:

~~~text
%LOCALAPPDATA%\ScarClipScheduler\
~~~

The publishing worker listens on the loopback interface (`127.0.0.1`) and requires a newly generated random token each time the app launches. Do not expose this local service to your LAN or the public internet.

- Never commit Google OAuth client JSON files, refresh tokens, Meta App Secrets, Page access tokens, database files, or logs.
- Never include credentials in GitHub issues, screenshots, or chat messages.
- Protect access to your Windows account and use disk encryption where appropriate.
- If a credential is exposed, revoke or rotate it in the relevant Google or Meta developer dashboard.
- Disconnecting inside ScarClipScheduler removes credentials from this PC only. Revoke the app's permissions from your Google or Meta account settings when you need to remove access at the platform level.

## Tests

Run the Python regression suite from the repository root (with the project dependencies installed):

~~~powershell
python -m py_compile app.py backend_service.py
python -m unittest discover -s tests -v
~~~

Build the native WPF desktop project:

~~~powershell
dotnet build .\native\ScarClipScheduler.Wpf\ScarClipScheduler.Wpf.csproj -c Release
~~~

## Project credits

**ScarClipScheduler** is created and maintained by **Sifat Jaman / ScarZero**, with development assistance from **ChatGPT by OpenAI**.

- [GitHub profile](https://github.com/sifat-jaman-13)
- [ScarClipScheduler source](https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler)
- [StreamSnip AI source](https://github.com/sifat-jaman-13/stream-clip-ai)
- [YouTube — Scar Clip Farm](https://youtube.com/@scarclipfarm)
- [YouTube — ScarZero](https://www.youtube.com/@scarzeroyt)
- [Instagram — @scarzero13](https://www.instagram.com/scarzero13/)
- [Facebook — ScarZero13](https://www.facebook.com/ScarZero13)
- [Twitch — scarzero13](https://www.twitch.tv/scarzero13)
- [TikTok — @scarzero13](https://www.tiktok.com/@scarzero13/)

ScarClipScheduler integrates with the official YouTube Data API and Meta Graph API. Publishing is still subject to each platform's API quotas, granted permissions, App Review requirements, account eligibility, and scheduling rules.


## License

ScarClipScheduler is available under a **proprietary non-commercial use licence**. Individual personal and educational use is permitted; company, organisational, and commercial use requires prior written permission. See [LICENSE](LICENSE) for the full terms.
