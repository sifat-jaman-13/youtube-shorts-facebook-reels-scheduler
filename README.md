# ScarClipScheduler

<p align="center">
  <img src="assets/scarclipscheduler-banner.svg" alt="ScarClipScheduler — Schedule Shorts and Reels with control" width="100%">
</p>


<p align="center">
  <a href="https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler?display_name=tag&sort=semver"></a>
  <a href="https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler/releases/latest/download/ScarClipScheduler-Setup.exe"><img alt="Windows installer" src="https://img.shields.io/badge/download-Windows%20installer-2563eb?logo=windows"></a>
  <a href="https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler/actions/workflows/build-exe.yml"><img alt="Windows build" src="https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler/actions/workflows/build-exe.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-22c55e"></a>
</p>

**Version 2.0.17 — Native Windows WPF desktop scheduler**

[Website](https://sifat-jaman-13.github.io/youtube-shorts-facebook-reels-scheduler/) · [GitHub repository](https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler) · [Latest release](https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler/releases/latest)

ScarClipScheduler manages a queue of MP4 clips and matching TXT metadata, then submits selected clips to YouTube Shorts and Facebook Page Reels using the official platform APIs.

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

- **Native Windows UI:** .NET 10 WPF. No Tkinter, no Qt and no embedded browser UI.
- **Separate publishing worker:** the existing Python publishing engine runs as a hidden background process. The WPF window stays independent while scanning, uploading, scheduling and verifying posts.
- **Responsive clip table:** row and column virtualization with incremental updates instead of clearing and rebuilding the full queue.
- **No support terminal:** normal operation does not open a terminal window. Use the built-in Activity log and status footer to monitor work.
- **Local-only worker API:** the WPF app communicates with the background worker through loopback on 127.0.0.1 using a per-launch random token.
- **One queue:** review YouTube and Facebook destination status together, including per-Page Facebook jobs.
- **Reconnect and disconnect:** connected accounts show their state and can be reconnected or disconnected from the Connections page.
- **Selective scheduling:** choose one clip, a group of clips, or the full queue.
- **Metadata editing:** review and edit the title and description for each selected video.
- **Schedule controls:** choose the first post date, select the hour and AM/PM, type minutes in the minute box, and set an interval in hours and minutes. Dates before today and first-post times that have already passed are rejected.
- **Separate Scheduled screen:** API-accepted clips leave Detected immediately and appear in a dedicated Scheduled list with accepted publish times for YouTube and each Facebook Page.
- **Safe to delete folder:** after every selected destination accepts the complete upload and returns its video/Reel ID, the MP4/TXT pair moves out of the watched source folder into `You can delete this`. A large green **SAFE TO DELETE** button opens that folder.
- **Clear history:** clear Scheduled rows from the app after a verified SQLite backup while preserving permanent upload receipts and SHA-256 duplicate protection.
- **Safe queue removal:** remove selected queue entries without cancelling posts already accepted by a platform.
- **Publication verification:** check platform status after the scheduled time.
- **About:** credits Sifat Jaman / ScarZero and ChatGPT by OpenAI and links to the creator's public GitHub projects and channels.

## Desktop application and background worker

The desktop application is a native WPF executable. It starts the Python publishing worker in the background with its console hidden. The worker binds only to 127.0.0.1 and selects an available local port.

The footer displays the worker and queue state. The **Activity log** page shows scan, upload, scheduling, verification and error messages. There is no separate support-terminal window to open or keep running.

Use **Quit** inside the app to close ScarClipScheduler. If a scan, upload or verification is active, the app asks before stopping and waits for the current operation to finish when possible. Do not end the worker process from Task Manager while a platform request is in progress.

## Scheduling workflow

1. Choose the folder containing your MP4 clips and same-basename TXT files.
2. Click **Scan clips** and review the detected videos.
3. Select one row or multiple rows. With no rows selected, the full queue is used.
4. Edit the selected clip's title and description if needed, then save the metadata.
5. Open **Connections** and connect YouTube and/or Facebook.
6. Select the Facebook Pages that should receive Reels.
7. Set the first post date and time, then set the posting interval. The allowed interval is **5 minutes through 24 hours**.
8. Click **Confirm start time**. The app saves the selected time and interval. Editing the date, time, or interval clears the confirmation; confirm again before scheduling.
9. Choose YouTube Shorts, Facebook Page Reels, or both. Confirm that you have the rights to publish the videos, then choose **Schedule queue** and approve the final summary.

The app uploads the videos now and asks the selected platform APIs to publish them at the requested times. A platform's accepted response is recorded as Scheduled; this means the API accepted the complete video and scheduled post, not that it is already public. As soon as every destination selected for a clip has accepted it and returned its external video/Reel ID, the MP4 and matching TXT are moved out of the watched source folder into `You can delete this` and the record leaves Detected. The separate Scheduled screen retains the clip, platform IDs and accepted publish times. The local files are no longer required for the accepted scheduled posts and can be manually deleted from that folder.

The first unaccepted clip uses the confirmed start time; each following clip uses the selected interval. The app does not silently replace the chosen time after a scan. The first post must be at least 15 minutes ahead of the current local time.

YouTube's daily upload quota can defer remaining YouTube work to the next quota window. Facebook uploads are attempted sequentially without an app-imposed per-day cap; the queue keeps going until Meta itself returns an API rejection. A definite Meta API rejection marks only that Page's clip as Failed and moves its publish slot to the immediately following local calendar day. Use **Reset failed** and start the queue again to retry the rejected clip. An ambiguous network outcome stays Partial and is locked against automatic re-upload until you verify it in Meta Business Suite. Already accepted platform schedules are never resubmitted.

The native app's **How to use** page explains MP4/TXT naming, automatic detection, the Detected-to-Scheduled workflow, the Safe to delete folder, and the effects of Clear history. The green **SAFE TO DELETE** button at the top opens the selected source folder's `You can delete this` subfolder in File Explorer.

### Upload history and duplicate protection (SQLite)

ScarClipScheduler keeps its publishing history in the local SQLite database:

~~~text
%LOCALAPPDATA%\ScarClipScheduler\queue.db
~~~

Version 2.0.15 adds a permanent upload ledger table. Its composite primary key is:

~~~sql
PRIMARY KEY (video_name, scheduled_at, platform, destination_id)
~~~

The platform identifies YouTube or Facebook, and the destination ID identifies the connected YouTube channel or Facebook Page. The ledger stores each upload's status, external video/session ID, attempt count, timestamps, and last error.

Each MP4 is also fingerprinted with SHA-256. A unique database index blocks the same file content from being claimed a second time for the same platform destination, even when the filename, source path, or scheduled time changes. Different Facebook Pages and a YouTube channel are separate destinations and therefore keep separate upload receipts.

Before sending an upload request, the worker atomically claims the ledger row as Uploading. Facebook's session ID is saved at the START stage, Uploaded is saved after the binary transfer, and Scheduled is saved only after the final scheduling request is accepted. YouTube is marked Scheduled when its upload API returns the accepted video ID.

When an upload fails with a definite platform rejection, it is marked Failed; **Reset failed** changes only those definite failures to retryable. An interrupted or ambiguous request becomes Partial (or remains Uploaded when the binary transfer was confirmed). Those states are intentionally not reset by **Reset failed**. Check YouTube Studio or Meta Business Suite before taking any further action; this is how the app avoids blindly sending a video again after an uncertain network response.

On first startup of 2.0.15, the app backs up the existing queue database to a backups folder next to it and migrates known YouTube video IDs and Facebook Page Reel IDs into the new ledger. Existing queue entries and per-Page history are preserved.

## Connections

### YouTube

Use Google Cloud OAuth 2.0 credentials for a Desktop application. Enable YouTube Data API v3, configure the OAuth consent screen, create a Desktop app OAuth client, and select its downloaded JSON file in the Connections page.

The app shows the connected channel name. **Reconnect YouTube** starts a fresh Google authorization. If that authorization fails, the previous local token is restored. **Disconnect** removes the saved local OAuth token and channel details from this PC; it does not cancel videos already accepted and scheduled by YouTube.

### Facebook Page Reels

Create a Meta developer app, configure the required Page permissions, and enter the Meta App ID, App Secret and Business Portfolio ID in the Connections page. Complete the browser authorization and select the Pages to publish to.

The app shows the Facebook connection state and the number of Pages available. **Reconnect Facebook** starts the authorization flow again. **Disconnect** removes saved Page tokens and connection details from this PC; it does not cancel Reels already accepted and scheduled by Facebook.

For Facebook Reels, the caption is assembled as the clip title, a blank line, then the full TXT description. ScarClipScheduler sends that exact same complete caption string in both Meta `title` and `description` fields. This avoids Facebook displaying only a trailing description fragment (for example, a “Clip from @creator” credit or hashtags) as the Reel's title.

Disconnecting is local to this installation. To revoke the app's permissions at the platform level, use the relevant Google or Facebook account settings.

## Clip folder and TXT format

Keep MP4 and TXT files directly inside the same selected folder. The filenames must match exactly:

~~~text
clips/
  highlight_001.mp4
  highlight_001.txt
  highlight_002.mp4
  highlight_002.txt
~~~

The first non-empty TXT line becomes the video title. The remaining lines become its description. A TXT file is optional; if none is found, the video filename is used as the title and the description is blank. Nested folders are not scanned.

## Queue statuses and file handling

- **Pending:** the selected destination has not started an upload.
- **Uploading:** an upload request is in progress.
- **Partial:** the upload stopped in an uncertain state, or a destination may have received the video without a confirmed final response. This state is locked against automatic re-upload.
- **Uploaded:** Facebook has accepted the binary upload stage, but the final scheduling request has not yet been confirmed. This state is locked against automatic re-upload.
- **Scheduled:** the destination has accepted the scheduled post.
- **Published:** publication was verified through the platform API.
- **Failed:** the platform returned a definite rejection before accepting the video. Review the Activity log, then use **Reset failed** when you are ready to retry.
- **Skipped:** the destination was skipped, for example because the clip failed the Facebook Reel format check.

The visible overall status is **Partial** when the selected destinations do not all share the same successful state. The YouTube and Facebook status columns still show each platform's own state.

**Detected** contains only clips that still need work for at least one selected destination. A clip accepted by every destination selected for that upload leaves Detected automatically.

**Scheduled** contains clips for which every selected destination accepted the complete upload through its API and returned a video/Reel ID. The list shows the publish time for each destination. Scheduled does not mean public; it means the platform has accepted the video and future publication request.

The MP4 and matching TXT are moved out of the scanned source folder into the `You can delete this` subfolder as soon as all selected destinations accept the complete upload and return their external IDs. This keeps them from being scanned and uploaded again. The top **SAFE TO DELETE** button opens that folder. Files in it are manual cleanup items: ScarClipScheduler does not permanently delete them. You may delete the local copies when you no longer need them; checking the platform's scheduled-content list is optional and does not control the local move.

If one or more selected destinations are still Pending, Failed, Partial, or uncertain, the clip stays in Detected and its source files remain available. It is moved only after all selected destinations have accepted it.

**Clear history** on the Scheduled screen removes the visible Scheduled rows from the app after creating and verifying a SQLite backup. It does not cancel or remove any post on YouTube/Meta, does not delete MP4/TXT files from `You can delete this`, and does not erase the permanent `upload_ledger`. External platform IDs and SHA-256 fingerprints remain protected so clearing the display cannot make an accepted video eligible for upload again.

**Delete from list** removes selected active local queue records and their per-Page job history. It does not delete source MP4/TXT files and does not cancel a post already accepted by YouTube or Meta.

## Before you install (Windows)

This checklist helps you prepare your PC before running setup. **It does not replace or disable the installer's own checks.** ScarClipScheduler-Setup.exe independently checks the required runtime during installation and attempts to install missing components through its visible PowerShell setup window.

### Requirements for normal installation

- **Operating system:** Windows 10 or Windows 11, 64-bit (x64).
- **Python:** 64-bit **CPython 3.10 or newer** for the local publishing worker. Setup checks the normal Windows `python` command on PATH with `python --version`. Python 3.10, 3.11, 3.12, 3.14, 3.15 and later compatible versions are accepted. If no compatible command is available, setup attempts to install Python 3.14 through WinGet.
- **WinGet / App Installer:** optional preferred installer when Python is missing. If WinGet is unavailable, setup downloads the latest stable 64-bit CPython installer directly from python.org, verifies its digital signature, and installs it for the current user.
- **Internet connection:** needed during first setup to install Python packages and later for Google / Meta API communication.
- **PowerShell:** included with Windows; setup opens it to display prerequisite checks and any automatic installation.
- **.NET:** no separate .NET runtime installation is required. The distributed WPF app is self-contained.
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

You may run these commands before starting the installer. The installer runs the same checks itself. If `python --version` returns a compatible 64-bit CPython 3.10+ version, no manual installation is needed.

~~~powershell
# Check the same command the installer checks
python --version

# Verify this is 64-bit CPython 3.10+
python -c "import sys; print(sys.executable); print(sys.implementation.name); print(sys.maxsize > 2**32); assert sys.implementation.name == 'cpython' and sys.version_info >= (3, 10) and sys.maxsize > 2**32"

# Check WinGet (used only if no compatible Python command is available)
winget --version
~~~

If `python --version` is missing or reports an unsupported runtime, setup first tries WinGet to install Python 3.14. If WinGet is not available or its installation fails, setup downloads the latest stable 64-bit Python installer directly from python.org, verifies the Python Software Foundation signature, installs it for the current user, and repeats the PATH check.

### Extra requirements for developers building from source

These tools are **not required** to install or run the published setup EXE. They are only needed when you clone, build, or compile the application yourself.

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

When you run **ScarClipScheduler-Setup.exe**, it opens a PowerShell setup window and:

1. runs `python --version` using the command resolved from the current Windows PATH, then validates that it is 64-bit CPython 3.10 or newer;
2. attempts to install Python automatically if the PATH command is missing or unsupported: WinGet first, then the official signed python.org installer if WinGet is unavailable or fails; it repeats the `python --version` check after installation;
3. creates or validates the app's isolated .venv;
4. checks the installed dependency set against the packaged requirements.txt;
5. installs or repairs packages only when the environment is new, incomplete, unhealthy, or the requirements have changed;
6. asks whether to launch ScarClipScheduler when setup is complete.

If prerequisite setup fails, the installer now stops instead of showing a successful Finish page. It saves diagnostics to `%LOCALAPPDATA%\\ScarClipScheduler\\installer-setup.log` and leaves the PowerShell window open so you can read the error.

This process runs **during installation only**. Opening ScarClipScheduler later starts the native WPF app and its background worker; it does not open the setup terminal or reinstall Python packages.

## Install and run

### New Windows installation (recommended)

Download **ScarClipScheduler-Setup.exe** from the [latest GitHub release](https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler/releases/latest).

1. Double-click **ScarClipScheduler-Setup.exe**. Do not extract a ZIP.
2. Follow the normal Windows installer prompts.
3. During installation, the PowerShell setup window opens automatically. It checks the required Python runtime and publishing-worker packages, then attempts to install anything missing.
4. When the setup window asks **Start ScarClipScheduler now?**, choose **Y** to launch it immediately. You can also start it later from the Start Menu or optional desktop shortcut.

The installer shows its dependency-check progress in PowerShell. If the required Python runtime and matching dependencies are already present and healthy, it reuses them and skips the package installation step. The dependency setup is not run when you open the app later.

The desktop executable is a self-contained .NET 10 WPF application; a separate .NET runtime installation is not required. The Python publishing worker runs in the background without a support-terminal window during normal app use.

### Existing Windows installation

The installed application and its virtual environment are stored under:

~~~text
%LOCALAPPDATA%\\Programs\\ScarClipScheduler\\
~~~

The queue database, scheduled-post IDs, settings, OAuth tokens, Meta credentials and logs remain in:

~~~text
%LOCALAPPDATA%\ScarClipScheduler\\
~~~

Updating the application replaces program files only. It does not delete the user-data folder or cancel posts already accepted by YouTube or Facebook. The installer refuses to replace files while ScarClipScheduler is running.

## Uninstall

Open **Start Menu → ScarClipScheduler → Uninstall ScarClipScheduler**, or use **Windows Settings → Apps → Installed apps → ScarClipScheduler → Uninstall**. The uninstaller removes the installed application files and shortcuts. It keeps your queue database, scheduled-post history, settings, OAuth tokens, Meta credentials, and logs in `%LOCALAPPDATA%\ScarClipScheduler` so that a later reinstall can reuse them.

### Run from source

Requirements:

- Windows 10/11 x64
- .NET 10 SDK
- Python 3.11 or 3.12 (64-bit)
- Internet access to install Python dependencies and use the platform APIs

Clone the repository and run the batch launcher:

~~~powershell
git clone https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler.git
cd youtube-shorts-facebook-reels-scheduler
.\\Start ScarClipScheduler.bat
~~~

Or set up and launch manually:

~~~powershell
py -3.11 -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
dotnet run --project .\\native\\ScarClipScheduler.Wpf\\ScarClipScheduler.Wpf.csproj
~~~

### Build the Windows installer

Run on Windows with the .NET 10 SDK and Inno Setup 6:

~~~powershell
.\build_windows_exe.ps1
~~~

The build creates **dist/installer/ScarClipScheduler-Setup.exe**. The single installer bundles the self-contained WPF application, Python publishing worker, dependency requirements, assets, and first-install PowerShell setup script. Credentials, queue data, and user settings are never included in the installer.


## Data and security

The app keeps local queue data, settings, logs and account tokens under:

~~~text
%LOCALAPPDATA%\ScarClipScheduler\
~~~

The publishing worker is bound to loopback and requires a fresh random token for each app launch. It is not intended to be exposed to the LAN or the public internet.

- Never commit Google OAuth client JSON files, refresh tokens, Meta App Secrets, Page access tokens, databases or logs.
- Do not paste credentials into GitHub issues, screenshots or chats.
- Keep Windows user-account access restricted and use disk encryption where appropriate.
- If a credential is exposed, revoke or rotate it in the relevant Google or Meta developer dashboard.
- Disconnecting in the app removes local credentials only; use the platform account settings to revoke permissions remotely.

## Tests

Run the Python regression suite:

~~~powershell
python -m py_compile app.py backend_service.py
python -m unittest discover -s tests -v
~~~

Build-check the native desktop project:

~~~powershell
dotnet build .\native\ScarClipScheduler.Wpf\ScarClipScheduler.Wpf.csproj -c Release
~~~

## Project credits

Created and maintained by **Sifat Jaman / ScarZero**. Development assistance from **ChatGPT by OpenAI**.

- [GitHub profile](https://github.com/sifat-jaman-13)
- [ScarClipScheduler source](https://github.com/sifat-jaman-13/youtube-shorts-facebook-reels-scheduler)
- [StreamSnip AI source](https://github.com/sifat-jaman-13/stream-clip-ai)
- [YouTube — Scar Clip Farm](https://youtube.com/@scarclipfarm)
- [YouTube — ScarZero](https://www.youtube.com/@scarzeroyt)
- [Instagram — @scarzero13](https://www.instagram.com/scarzero13/)
- [Facebook — ScarZero13](https://www.facebook.com/ScarZero13)
- [Twitch — scarzero13](https://www.twitch.tv/scarzero13)
- [TikTok — @scarzero13](https://www.tiktok.com/@scarzero13/)

ScarClipScheduler uses the official Google YouTube Data API and Meta Graph API. Platform quotas, permissions, App Review, account eligibility and scheduling restrictions still apply.


## License

ScarClipScheduler is open source under the **MIT License**. See the [LICENSE](LICENSE) file for the full terms.
