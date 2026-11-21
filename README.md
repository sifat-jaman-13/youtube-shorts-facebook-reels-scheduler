# ScarClipScheduler

**A Windows desktop app for scheduling YouTube Shorts and Facebook Page Reels from one local queue.**

ScarClipScheduler scans rendered MP4 clips and their matching TXT metadata, lets you review and edit every title and description, then schedules selected clips to a YouTube channel and one or more Facebook Pages. It keeps the queue, credentials, and working files on your Windows PC.

> This project is an API-based scheduler. It does not automate browser clicks to upload videos. Platform APIs, permissions, quotas, account status, and publishing eligibility determine what can be scheduled.

## Features

- **One queue for two platforms:** schedule YouTube videos and Facebook Page Reels from the same clip list.
- **Multi-Page Facebook publishing:** select several Pages and track each Page's result separately.
- **TXT-based metadata:** pair each `.mp4` with a same-name `.txt`; the first non-empty line is the title and the remaining text becomes the description.
- **Review before scheduling:** edit titles/descriptions in the queue without rewriting the original metadata file.
- **Queue timeline:** choose a starting time and schedule posts at the configured interval (five minutes by default).
- **Per-clip status:** Pending, Partial, Scheduled, Published, Uploaded, Failed, or Skipped. Completed statuses are visually marked and sorted below pending work.
- **Publication verification:** check platform-side status after the planned publication time instead of treating an accepted schedule request as a published post.
- **Safer file organization:** separates accepted scheduled files from unfinished source files and provides a final manual-review folder after the complete recorded queue has been verified.
- **Local-first storage:** the queue database and authorization data are stored under your Windows user profile.

## Requirements

- Windows 10 or later.
- Python 3.11 or newer, available as `python` on PATH.
- Internet access for Google and Meta authentication, API requests, and video uploads.
- A Google Cloud project with the YouTube Data API v3 enabled.
- A Meta developer app with Page publishing access to the Pages you intend to use.
- MP4 clips and matching TXT files. The app uses FFprobe when available to validate Facebook Reel format.

## Install and launch

1. Download or clone this repository to a folder on your PC.
2. Install Python 3.11 or newer and enable **Add Python to PATH** during installation.
3. Double-click **Start ScarClipScheduler.bat**.
4. On first launch, the batch file creates a local `.venv` and installs the packages in `requirements.txt`.
5. Open **Connections** and connect the platforms you plan to use.

The launcher runs the application with its isolated virtual environment. You do not need to activate the environment manually.

### Run from PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python app.py
```

## Connect YouTube

ScarClipScheduler uses the official **YouTube Data API v3** and Google OAuth 2.0. Upload access is authorized through your Google account; do not give the app your Google password.

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create or select a project.
2. Open **APIs & Services → Library** and enable **YouTube Data API v3**.
3. Configure the OAuth consent screen and add your Google account as a test user while the app is in testing.
4. Open **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
5. Choose **Desktop app**, create the client, and download its JSON file.
6. In ScarClipScheduler, open **Connections → YouTube**, browse to that JSON file, and click **Connect YouTube**.
7. Sign in to the Google account that owns the intended channel and approve the requested YouTube permissions.
8. Confirm the connected channel shown in the app is the correct one.

**Important OAuth note:** Google documents that refresh tokens for an External OAuth consent screen left in **Testing** expire after seven days when the app requests scopes beyond basic identity/profile scopes. This app requests YouTube scopes. For longer-term use, review Google's publishing-status and verification requirements and move the OAuth app out of Testing where appropriate. [Google OAuth token lifetime guidance](https://developers.google.com/identity/protocols/oauth2#expiration).

**YouTube scheduling behaviour:** scheduled videos are uploaded as private with a `status.publishAt` time. Google's API only allows `publishAt` when the video's privacy status is private and the video has not previously been published. See the [YouTube video status resource](https://developers.google.com/youtube/data/reference/rest/v3/videos).

**Quota:** the current default YouTube Data API quota has a separate `videos.insert` upload bucket of 100 calls per day, resetting at midnight Pacific Time. ScarClipScheduler accounts for the daily upload allowance and spaces the queue. Check your own Google Cloud quota page because project allocations and policy can change. [Official quota calculator](https://developers.google.com/youtube/data/determine_quota_cost).

## Connect Facebook Pages

ScarClipScheduler uses the **Meta Graph API** to publish Reels to Facebook Pages. The app is configured for Graph API `v27.0`.

1. Open [Meta for Developers](https://developers.facebook.com/apps/) and create a Meta app for your Page-publishing use case.
2. Add the relevant Page-management / Facebook Login capabilities in the app dashboard.
3. Configure the OAuth redirect URI exactly as:
   `http://localhost:8765/callback`
4. Ensure the app can request these permissions:
   - `pages_show_list` — find Pages available to the signed-in account.
   - `pages_manage_posts` — publish and schedule Page content.
   - `pages_read_engagement` — read Page publishing/status information.
   - `business_management` — discover Pages owned by the selected Business Portfolio.
5. In ScarClipScheduler → **Connections → Facebook**, enter your Meta **App ID**, **Business Portfolio ID**, and **App Secret**. Enter the App Secret only in the app on your own PC.
6. Click **Connect & Load Business Pages**, complete Facebook authorization, and approve the requested access.
7. Select the Facebook Pages that should receive the clips. Each selected Page is handled as a separate destination with its own result.

The Facebook account used to connect must have the Page task/access needed to create content on each selected Page. The Page Videos API documents the `CREATE_CONTENT` task and the `pages_manage_posts`, `pages_read_engagement`, and `pages_show_list` permissions for publishing. See [Meta Page Videos](https://developers.facebook.com/docs/graph-api/reference/page/videos/) and [Page Feed publishing requirements](https://developers.facebook.com/docs/graph-api/reference/page/feed/).

**Development mode:** while a Meta app is in Development mode, access is limited to people with a role on the app. If you intend to let people outside the app's roles use your integration, review Meta's Standard/Advanced Access and App Review requirements before switching the app to production. See [Meta's app development lifecycle](https://developers.facebook.com/docs/apps/managing-development-cycle/) and [App Review overview](https://developers.facebook.com/docs/resp-plat-initiatives/app-review/introduction/).

**Facebook scheduling window:** Meta's current Page Videos reference documents scheduled publication from 10 minutes to 6 months ahead. ScarClipScheduler deliberately applies a narrower internal planning window (at least 15 minutes ahead and no more than 29 days) as an application-side guardrail. Platform policies and eligibility can change; check the Meta dashboard if a request is rejected.

## Prepare the clip folder

1. In **Connections / Publishing queue**, set the folder containing your rendered clips.
2. Keep each video and its metadata file together, for example:

```text
source/
  highlight_001.mp4
  highlight_001.txt
  highlight_002.mp4
  highlight_002.txt
```

3. Click **Scan clips**.
4. Check the title and description for every detected clip. You can edit them in the queue.
5. Select the YouTube channel, Facebook Pages, or both.
6. Choose the starting date/time and confirm the queue interval.
7. Confirm that you own the footage or have the rights and permission to publish it.
8. Review the queue, then click **Schedule queue**.

A matching TXT file should be UTF-8 text with the title on its first non-empty line and the description below it. A simple example:

```text
The Most Unexpected Comeback

An incredible moment from the stream.
#shorts #gaming #clips
```

## Scheduling, status, and safe cleanup

- A successful API response means **Scheduled** or **Uploaded**, not that the post is already public.
- The app checks publication status through the platform APIs after the scheduled time, allowing a five-minute grace period.
- Automatic status checks run after startup and every 15 minutes while the app is open. You can also use **Check publication status** from the queue.
- If the PC is off when a post becomes due, a schedule already accepted by the platform can still publish. The app resumes local verification when it is opened again.
- Accepted scheduled MP4/TXT pairs are moved to the source folder's `schedule` subfolder. Pending, failed, skipped, and partially accepted items remain available for review.
- The `You can delete these clips now` folder is a queue-wide manual-review area. The app waits until every recorded destination across the scheduled timeline is verified as Published before moving the completed batch there.
- **ScarClipScheduler does not automatically delete your videos.** Inspect the public posts and manually delete local files only when you are sure you no longer need them.
- An `uploaded` folder is created for the Uploaded-only workflow/status.

## Local data and security

The app stores its operational data under:

```text
%LOCALAPPDATA%\ScarClipScheduler\
```

This location contains the queue database, settings, Google OAuth client/authorization data, YouTube token data, and logs. Treat the folder as private.

- Never commit OAuth client JSON, refresh tokens, Meta App Secrets, Page access tokens, queue databases, or application logs.
- Do not paste credentials into GitHub issues, screenshots, chat messages, or README files.
- If a credential is exposed, revoke or rotate it in the relevant Google or Meta dashboard.
- The repository's `.gitignore` excludes local environments, backups, runtime state, logs, credentials, and generated videos.

## Troubleshooting

| Problem | What to check |
|---|---|
| YouTube authorization fails | Re-check the OAuth Desktop client JSON, consent-screen test users, requested scopes, and connected Google account. |
| YouTube refresh token stops working | Check whether the OAuth consent screen is still in Testing and review Google's seven-day testing-token rule. |
| Facebook Pages do not load | Check the Business Portfolio ID, app role, Page access, `business_management`, and `pages_show_list`; reconnect to refresh permissions. |
| Facebook permission error | Verify `pages_manage_posts`, `pages_read_engagement`, Page `CREATE_CONTENT` access, and Meta App Review/Access level. |
| Facebook OAuth callback fails | Ensure port 8765 is available and the redirect URI matches exactly. |
| Video is rejected as a Reel | Confirm a vertical 9:16 MP4 in the app's supported conservative duration range (4–60 seconds). |
| Upload seems stalled | Keep the app open, check the internet connection, and inspect the app log. Do not blindly reset or retry an item until you have checked whether the platform accepted it. |

Detailed log: `%LOCALAPPDATA%\ScarClipScheduler\app.log`.

## Project files

```text
ScarClipScheduler/
  app.py
  requirements.txt
  Start ScarClipScheduler.bat
  README.md
```

## Responsible publishing

Only publish clips you own or are licensed/authorized to distribute. Giving credit does not automatically grant permission. Review music, gameplay, streamer, and third-party rights as well as each platform's reused-content and monetization policies. ScarClipScheduler is a scheduling utility, not a rights or policy checker.

## Platform documentation

- [YouTube Data API authorization](https://developers.google.com/youtube/data/guides/authentication)
- [YouTube Data API video upload](https://developers.google.com/youtube/data/guides/uploading_a_video)
- [YouTube API quota](https://developers.google.com/youtube/data/determine_quota_cost)
- [Google OAuth 2.0 refresh-token expiration](https://developers.google.com/identity/protocols/oauth2#expiration)
- [Meta Page Videos API](https://developers.facebook.com/docs/graph-api/reference/page/videos/)
- [Meta Page Feed API](https://developers.facebook.com/docs/graph-api/reference/page/feed/)
- [Meta App Review](https://developers.facebook.com/docs/resp-plat-initiatives/app-review/introduction/)

---

**ScarClipScheduler** · Python desktop automation for YouTube Shorts and Facebook Page Reels scheduling.
