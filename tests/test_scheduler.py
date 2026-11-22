import json
import sqlite3
import struct
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from unittest.mock import Mock, patch

import app
import backend_service


class SchedulerRegressionTests(unittest.TestCase):
    def test_video_sidecar_uses_the_same_basename_with_txt_extension(self):
        video = Path("clips") / "highlight_001.mp4"
        self.assertEqual(
            app.clip_sidecar_path(video),
            Path("clips") / "highlight_001.txt"
        )

    def test_clip_selection_summary_explains_single_batch_and_full_queue(self):
        self.assertEqual(
            app.clip_selection_summary(0),
            "0 selected | entire queue will be scheduled"
        )
        self.assertEqual(
            app.clip_selection_summary(1),
            "1 selected | one clip will be scheduled"
        )
        self.assertEqual(
            app.clip_selection_summary(4),
            "4 selected | batch scheduling"
        )

    def test_native_wpf_frontend_is_virtualized_and_has_connection_controls(self):
        project = Path(app.__file__).resolve().parent
        native = project / "native" / "ScarClipScheduler.Wpf"
        xaml = (native / "MainWindow.xaml").read_text(encoding="utf-8")
        code = (native / "MainWindow.xaml.cs").read_text(encoding="utf-8")
        backend = (project / "backend_service.py").read_text(encoding="utf-8")
        client = (native / "BackendClient.cs").read_text(encoding="utf-8")
        csproj = (native / "ScarClipScheduler.Wpf.csproj").read_text(encoding="utf-8")

        self.assertIn("TargetFramework>net10.0-windows", csproj)
        self.assertIn('x:Name="StartHour"', xaml)
        self.assertIn('x:Name="StartMinute"', xaml)
        self.assertIn('x:Name="StartAmPm"', xaml)
        self.assertIn('PreviewTextInput="StartMinute_PreviewTextInput"', xaml)
        self.assertIn("StartMinute_PreviewTextInput", code)
        self.assertNotIn('x:Name="StartTime"', xaml)
        self.assertNotIn("Next 5:00 AM", xaml)
        self.assertNotIn("NextFiveAm_Click", code)
        self.assertNotIn("Next 5:00 AM", (project / "README.md").read_text(encoding="utf-8"))
        self.assertIn("StartDate.DisplayDateStart = DateTime.Today", code)
        self.assertIn("GetSelectedStartDateTime()", code)
        self.assertIn("SetDefaultStartTime()", code)
        self.assertIn("validate_future_start_at(data.get(\"start_at\"))", backend)
        self.assertIn("EnableRowVirtualization", xaml)
        self.assertIn("VirtualizingPanel.VirtualizationMode", xaml)
        self.assertIn("Clips.Insert", code)
        self.assertIn("Reconnect YouTube", code)
        self.assertIn("Reconnect Facebook", code)
        self.assertIn("DisconnectYoutube_Click", xaml)
        self.assertIn("DisconnectFacebook_Click", xaml)
        self.assertIn("YoutubeConnecting", code)
        self.assertIn("FacebookConnecting", code)
        self.assertIn("reconnect-backup", backend)
        self.assertIn("interactive=True", backend)
        self.assertIn('"/api/disconnect-youtube"', backend)
        self.assertIn('"/api/disconnect-facebook"', backend)
        self.assertIn("scheduled_posts_preserved", backend)
        self.assertIn("CreateNoWindow = true", client)
        self.assertIn('PostConfirmedAsync("api/schedule", settings)', code)
        self.assertIn("PostConfirmedAsync(", client)
        self.assertIn('"X-Scar-User-Confirmed"', client)
        self.assertIn('self.headers.get("X-Scar-User-Confirmed"', backend)
        self.assertIn('if data.get("confirmed") is not True:', backend)
        self.assertIn("Desktop version", client)
        self.assertIn("About_Click", xaml)
        self.assertNotIn("Support terminal", xaml)
        self.assertNotIn("SupportConsole_Click", code)
        self.assertIn("Sifat Jaman / ScarZero", code)
        self.assertIn("ChatGPT by OpenAI", code)
        self.assertIn("https://github.com/sifat-jaman-13", code)
        self.assertIn('https://www.youtube.com/channel/{Uri.EscapeDataString(_state.YoutubeChannelId)}', code)
        self.assertNotIn("foreach (var page in _state.FacebookPages)", code)
        self.assertNotIn("CONNECTED FACEBOOK PAGES", code)
        self.assertNotIn("Platform publishing uses your own Google and Meta authorization", code)
        self.assertNotIn("support_console.ps1", csproj)

    def test_local_disconnect_removes_tokens_but_preserves_scheduled_database(self):
        from unittest.mock import Mock

        class Idle:
            def is_alive(self):
                return False

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token = root / "youtube_token.json"
            credentials = root / "credentials.json"
            database = root / "queue.db"
            token.write_text('{"refresh_token":"test"}', encoding="utf-8")
            credentials.write_text(
                '{"yt_channel_title":"Test channel","yt_channel_id":"yt-id",'
                '"fb_pages":[{"id":"page-id","access_token":"page-token"}],'
                '"fb_page_access_token":"legacy-token","fb_page_id":"page-id",'
                '"fb_page_name":"Test Page"}',
                encoding="utf-8"
            )
            db = sqlite3.connect(database)
            db.execute("CREATE TABLE scheduled(id INTEGER PRIMARY KEY, platform_id TEXT)")
            db.executemany("INSERT INTO scheduled(platform_id) VALUES (?)", [("yt-id",), ("fb-id",)])
            db.commit()
            before = db.execute("SELECT COUNT(*) FROM scheduled").fetchone()[0]
            db.close()

            fake = SimpleNamespace(
                worker=Idle(), scan_worker=Idle(), verification_worker=Idle(),
                secrets={
                    "yt_channel_title": "Test channel", "yt_channel_id": "yt-id",
                    "fb_pages": [{"id": "page-id", "access_token": "page-token"}],
                    "fb_page_access_token": "legacy-token", "fb_page_id": "page-id",
                    "fb_page_name": "Test Page"
                },
                settings={"fb_selected_page_ids": ["page-id"]},
                log=Mock(), refresh_connections=Mock(), save_settings=Mock(),
                _ensure_idle_for_disconnect=lambda: None
            )
            with patch.object(app, "YT_TOKEN_PATH", token), patch.object(app, "CREDENTIALS_PATH", credentials):
                backend_service.NativeBackend.disconnect_youtube(fake)
                self.assertFalse(token.exists())
                self.assertEqual(fake.secrets["yt_channel_title"], "")
                backend_service.NativeBackend.disconnect_facebook(fake)
                self.assertNotIn("fb_pages", fake.secrets)
                self.assertNotIn("fb_page_access_token", fake.secrets)

            db = sqlite3.connect(database)
            after = db.execute("SELECT COUNT(*) FROM scheduled").fetchone()[0]
            db.close()
            self.assertEqual(before, after)
            self.assertEqual(after, 2)

    def test_youtube_reconnect_forces_oauth_and_restores_or_replaces_token_safely(self):
        from unittest.mock import Mock

        class InlineThread:
            def __init__(self, target, daemon=True):
                self.target = target
            def start(self):
                self.target()
            def is_alive(self):
                return False

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token = root / "youtube_token.json"
            credentials_file = root / "credentials.json"
            token.write_text("old-valid-token", encoding="utf-8")
            credentials_file.write_text("{}", encoding="utf-8")

            def make_backend(load_credentials):
                return SimpleNamespace(
                    _ensure_idle_for_auth=lambda: None,
                    apply_settings=Mock(),
                    load_youtube_credentials=load_credentials,
                    log=Mock(),
                    emit=Mock(),
                    refresh_connections=Mock(),
                    dialogs=SimpleNamespace(showerror=Mock()),
                    youtube_auth_worker=None,
                    secrets={"yt_channel_title": "Old channel", "yt_channel_id": "old-id"}
                )

            with patch.object(app, "YT_TOKEN_PATH", token), patch.object(app, "CREDENTIALS_PATH", credentials_file), patch.object(backend_service.threading, "Thread", InlineThread):
                failed = make_backend(Mock(side_effect=RuntimeError("OAuth cancelled")))
                backend_service.NativeBackend.connect_youtube(failed, {})
                self.assertEqual(token.read_text(encoding="utf-8"), "old-valid-token")
                self.assertFalse(token.with_name(token.name + ".reconnect-backup").exists())

                def successful_oauth(interactive=False):
                    self.assertTrue(interactive)
                    token.write_text("new-token", encoding="utf-8")
                    return object()

                service = SimpleNamespace(
                    channels=lambda: SimpleNamespace(
                        list=lambda **_kwargs: SimpleNamespace(
                            execute=lambda: {"items": [{"id": "new-id", "snippet": {"title": "New channel"}}]}
                        )
                    )
                )
                with patch("googleapiclient.discovery.build", return_value=service):
                    successful = make_backend(successful_oauth)
                    backend_service.NativeBackend.connect_youtube(successful, {})
                self.assertEqual(token.read_text(encoding="utf-8"), "new-token")
                self.assertEqual(successful.secrets["yt_channel_title"], "New channel")
                self.assertEqual(successful.secrets["yt_channel_id"], "new-id")
                self.assertFalse(token.with_name(token.name + ".reconnect-backup").exists())

    def test_post_interval_supports_hours_and_minutes_up_to_one_day(self):
        self.assertEqual(app.MAX_INTERVAL_MINUTES, 1440)
        self.assertEqual(app.MAX_INTERVAL_MINUTES // 60, 24)

    def test_youtube_slot_allocator_accepts_hour_based_intervals(self):
        start = datetime.now().astimezone() + timedelta(hours=1)
        self.assertEqual(app.allocate_youtube_publish_slots([], start, 180), {})

    def test_native_ui_uses_a_hidden_background_python_worker(self):
        project = Path(app.__file__).resolve().parent
        client = (project / "native" / "ScarClipScheduler.Wpf" / "BackendClient.cs").read_text(encoding="utf-8")
        main = (project / "native" / "ScarClipScheduler.Wpf" / "MainWindow.xaml.cs").read_text(encoding="utf-8")
        self.assertIn("UseShellExecute = false", client)
        self.assertIn("CreateNoWindow = true", client)
        self.assertIn("backend_service.py", client)
        self.assertIn("Waiting for the current upload / scan / verification request", main)

    def test_native_ui_does_not_launch_a_support_terminal(self):
        project = Path(app.__file__).resolve().parent
        main = (project / "native" / "ScarClipScheduler.Wpf" / "MainWindow.xaml.cs").read_text(encoding="utf-8")
        xaml = (project / "native" / "ScarClipScheduler.Wpf" / "MainWindow.xaml").read_text(encoding="utf-8")
        project_file = (project / "native" / "ScarClipScheduler.Wpf" / "ScarClipScheduler.Wpf.csproj").read_text(encoding="utf-8")
        self.assertNotIn("StartSupportConsole", main)
        self.assertNotIn("SupportConsole_Click", main)
        self.assertNotIn("Support terminal", xaml)
        self.assertNotIn("support_console.ps1", project_file)
        self.assertFalse((project / "support_console.ps1").exists())

    def test_about_credits_creator_chatgpt_and_uses_connected_channel_id(self):
        project = Path(app.__file__).resolve().parent
        main = (project / "native" / "ScarClipScheduler.Wpf" / "MainWindow.xaml.cs").read_text(encoding="utf-8")
        backend = (project / "backend_service.py").read_text(encoding="utf-8")
        models = (project / "native" / "ScarClipScheduler.Wpf" / "Models.cs").read_text(encoding="utf-8")
        self.assertIn("Sifat Jaman / ScarZero", main)
        self.assertIn("ChatGPT by OpenAI", main)
        self.assertIn('var facebookHeader = state.FacebookConnecting', main)
        self.assertIn('FB: {state.FacebookPages.Count} Pages', main)
        self.assertNotIn('CONNECTED FACEBOOK PAGES', main)
        self.assertNotIn('foreach (var page in _state.FacebookPages)', main)
        self.assertNotIn('ChatGPT does not receive or store those credentials', main)
        self.assertIn("youtube-shorts-facebook-reels-scheduler", main)
        self.assertIn("stream-clip-ai", main)
        self.assertIn("youtube_channel_id", backend)
        self.assertIn("YoutubeChannelId", models)

    def test_stop_queue_requests_graceful_stop_and_disables_button(self):
        class FakeEvent:
            def __init__(self):
                self.was_set = False
            def set(self):
                self.was_set = True

        class FakeWorker:
            def is_alive(self):
                return True

        class FakeButton:
            def __init__(self):
                self.options = {}
            def configure(self, **kwargs):
                self.options.update(kwargs)

        messages = []
        fake = SimpleNamespace(
            worker=FakeWorker(),
            stop_event=FakeEvent(),
            stop_button=FakeButton(),
            log=messages.append
        )
        app.SchedulerApp.stop_scheduling(fake)
        self.assertTrue(fake.stop_event.was_set)
        self.assertEqual(fake.stop_button.options, {
            "state": "disabled",
            "text": "Stopping..."
        })
        self.assertTrue(any("active platform upload will finish" in m for m in messages))

    def test_stop_queue_when_idle_does_not_signal_a_worker(self):
        class FakeEvent:
            def __init__(self):
                self.was_set = False
            def set(self):
                self.was_set = True

        class FakeButton:
            def __init__(self):
                self.options = {}
            def configure(self, **kwargs):
                self.options.update(kwargs)

        fake = SimpleNamespace(
            worker=None,
            stop_event=FakeEvent(),
            stop_button=FakeButton(),
            log=lambda _message: None
        )
        app.SchedulerApp.stop_scheduling(fake)
        self.assertFalse(fake.stop_event.was_set)
        self.assertEqual(fake.stop_button.options, {
            "state": "disabled",
            "text": "Stop queue"
        })

    def test_branded_app_icon_is_valid_and_embedded_in_windows_package(self):
        project = Path(app.__file__).resolve().parent
        logo_path = project / "assets" / "scarclipscheduler-logo.png"
        icon_path = project / "assets" / "scarclipscheduler.ico"
        self.assertTrue(logo_path.is_file())
        self.assertTrue(icon_path.is_file())
        self.assertEqual(logo_path.read_bytes()[:8], bytes((137, 80, 78, 71, 13, 10, 26, 10)))
        icon = icon_path.read_bytes()
        self.assertGreaterEqual(len(icon), 1000)
        reserved, icon_type, count = struct.unpack("<HHH", icon[:6])
        self.assertEqual((reserved, icon_type), (0, 1))
        self.assertGreaterEqual(count, 3)
        native = project / "native" / "ScarClipScheduler.Wpf"
        csproj = (native / "ScarClipScheduler.Wpf.csproj").read_text(encoding="utf-8")
        window = (native / "MainWindow.xaml.cs").read_text(encoding="utf-8")
        self.assertIn("scarclipscheduler.ico", csproj)
        self.assertIn("scarclipscheduler-logo.png", csproj)
        self.assertIn("BitmapFrame.Create", window)

    def setUp(self):
        self.now = datetime(2026, 11, 22, 12, 0, tzinfo=ZoneInfo("Asia/Dhaka"))

    def test_youtube_retry_reallocates_expired_and_missing_publish_times(self):
        rows = [
            {"path": "accepted.mp4", "yt_status": "Scheduled",
             "publish_at": (self.now + timedelta(minutes=30)).isoformat()},
            {"path": "future.mp4", "yt_status": "Error",
             "publish_at": (self.now + timedelta(hours=1)).isoformat()},
            {"path": "expired.mp4", "yt_status": "Error",
             "publish_at": (self.now - timedelta(hours=1)).isoformat()},
            {"path": "missing.mp4", "yt_status": "Pending", "publish_at": None},
        ]
        start = self.now + timedelta(minutes=20)
        with patch.object(app, "local_now", return_value=self.now):
            slots = app.allocate_youtube_publish_slots(rows, start, 5, now=self.now)

        self.assertEqual(set(slots), {"expired.mp4", "missing.mp4"})
        self.assertEqual(rows[0]["publish_at"], (self.now + timedelta(minutes=30)).isoformat())
        self.assertEqual(rows[1]["publish_at"], (self.now + timedelta(hours=1)).isoformat())
        self.assertGreater(datetime.fromisoformat(slots["expired.mp4"]), self.now + timedelta(hours=1))
        self.assertGreater(datetime.fromisoformat(slots["missing.mp4"]),
                           datetime.fromisoformat(slots["expired.mp4"]))

    def test_youtube_retry_never_reschedules_an_accepted_post(self):
        rows = [
            {"path": "accepted.mp4", "yt_status": "Scheduled", "publish_at": None},
            {"path": "done.mp4", "yt_status": "Published", "publish_at": None},
        ]
        with patch.object(app, "local_now", return_value=self.now):
            slots = app.allocate_youtube_publish_slots(
                rows, self.now + timedelta(minutes=30), 5, now=self.now
            )
        self.assertEqual(slots, {})

    def test_youtube_allocator_keeps_each_pacific_day_at_or_below_100(self):
        start = app.next_pacific_midnight(self.now) + timedelta(hours=4)
        rows = [
            {"path": f"clip_{index:03}.mp4", "yt_status": "Pending", "publish_at": None}
            for index in range(208)
        ]
        slots = app.allocate_youtube_publish_slots(rows, start, 5, now=self.now)
        self.assertEqual(len(slots), 208)
        pacific = ZoneInfo("America/Los_Angeles")
        daily = {}
        for value in slots.values():
            day = datetime.fromisoformat(value).astimezone(pacific).date()
            daily[day] = daily.get(day, 0) + 1
        self.assertEqual(sorted(daily.values()), [8, 100, 100])
        self.assertLessEqual(max(daily.values()), 100)

    def test_youtube_allocator_moves_to_next_pacific_day_when_existing_day_is_full(self):
        pacific = ZoneInfo("America/Los_Angeles")
        quota_now = datetime(2026, 11, 22, 3, 0, tzinfo=pacific)
        first = quota_now + timedelta(hours=1)
        day = first.date()
        rows = [
            {"path": f"accepted_{index}.mp4", "yt_status": "Scheduled",
             "publish_at": (first + timedelta(minutes=index * 5)).isoformat()}
            for index in range(100)
        ]
        rows.append({"path": "retry.mp4", "yt_status": "Error", "publish_at": None})
        with patch.object(app, "local_now", return_value=quota_now):
            slots = app.allocate_youtube_publish_slots(
                rows, first, 5, now=quota_now
            )
        assigned = datetime.fromisoformat(slots["retry.mp4"]).astimezone(pacific)
        self.assertGreater(assigned.date(), day)
        self.assertEqual((assigned.hour, assigned.minute), (4, 0))

    def test_parse_txt_uses_first_nonempty_line_as_title_and_rest_as_description(self):
        with tempfile.TemporaryDirectory() as directory:
            txt = Path(directory) / "clip.txt"
            txt.write_text(
                "\ufeff\nA strong clip title\n\nFull transcript.\n#shorts\n"
                "Clip: clip.mp4\nTimestamp: 00:00:12 - 00:00:47\n",
                encoding="utf-8"
            )
            title, description = app.parse_txt(txt)
        self.assertEqual(title, "A strong clip title")
        self.assertIn("Full transcript.", description)
        self.assertIn("Timestamp:", description)

    def test_parse_txt_truncates_title_to_youtube_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            txt = Path(directory) / "clip.txt"
            txt.write_text("T" * 140 + "\nDescription", encoding="utf-8")
            title, description = app.parse_txt(txt)
        self.assertLessEqual(len(title), 100)
        self.assertEqual(description, "Description")

    def test_queue_status_requires_every_selected_destination(self):
        row = {"path": "clip.mp4", "yt_status": "Scheduled"}
        page_jobs = {
            ("clip.mp4", "page-a"): {"status": "Scheduled"},
            ("clip.mp4", "page-b"): {"status": "Pending"},
        }
        pages = [{"id": "page-a"}, {"id": "page-b"}]
        self.assertEqual(
            app.SchedulerApp.get_queue_row_status(row, page_jobs, pages, True, True),
            "◐ Partial"
        )
        page_jobs[("clip.mp4", "page-b")]["status"] = "Scheduled"
        self.assertEqual(
            app.SchedulerApp.get_queue_row_status(row, page_jobs, pages, True, True),
            "✓ Scheduled"
        )
        row["yt_status"] = "Published"
        page_jobs[("clip.mp4", "page-a")]["status"] = "Published"
        page_jobs[("clip.mp4", "page-b")]["status"] = "Published"
        self.assertEqual(
            app.SchedulerApp.get_queue_row_status(row, page_jobs, pages, True, True),
            "✓ Published"
        )

    def test_queue_status_marks_any_failed_destination_failed(self):
        row = {"path": "clip.mp4", "yt_status": "Scheduled"}
        jobs = {("clip.mp4", "page-a"): {"status": "Error"}}
        self.assertEqual(
            app.SchedulerApp.get_queue_row_status(
                row, jobs, [{"id": "page-a"}], True, True
            ),
            "⚠ Failed"
        )

    def test_safe_cleanup_gate_requires_every_recorded_destination_published(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = app.SchedulerApp.__new__(app.SchedulerApp)
            instance.db_lock = threading.Lock()
            instance.conn = sqlite3.connect(":memory:")
            instance.conn.row_factory = sqlite3.Row
            instance.create_db()
            path_a = str(Path(directory) / "a.mp4")
            path_b = str(Path(directory) / "b.mp4")
            instance.db_execute(
                "INSERT INTO clips(path,title,description,yt_status,yt_video_id,publish_at) "
                "VALUES(?,?,?,?,?,?)",
                (path_a, "A", "", "Published", "yt-a", self.now.isoformat())
            )
            instance.db_execute(
                "INSERT INTO clips(path,title,description,yt_status,yt_video_id,publish_at) "
                "VALUES(?,?,?,?,?,?)",
                (path_b, "B", "", "Published", "yt-b", self.now.isoformat())
            )
            instance.db_execute(
                "INSERT INTO facebook_page_jobs(path,page_id,page_name,publish_at,status,video_id) "
                "VALUES(?,?,?,?,?,?)",
                (path_b, "page-a", "Page A", self.now.isoformat(), "Scheduled", "fb-b")
            )
            self.assertFalse(instance.all_recorded_destinations_published())
            instance.db_execute(
                "UPDATE facebook_page_jobs SET status='Published' WHERE path=?",
                (path_b,)
            )
            self.assertTrue(instance.all_recorded_destinations_published())
            instance.conn.close()

    def test_move_clip_files_moves_mp4_txt_and_database_paths_together(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "clip.mp4"
            txt = root / "clip.txt"
            video.write_bytes(b"test mp4")
            txt.write_text("Title\nDescription", encoding="utf-8")

            instance = app.SchedulerApp.__new__(app.SchedulerApp)
            instance.db_lock = threading.Lock()
            instance.conn = sqlite3.connect(":memory:")
            instance.conn.row_factory = sqlite3.Row
            instance.create_db()
            instance.folder_var = SimpleNamespace(get=lambda: str(root))
            instance.selected_path = str(video)
            instance.txt_preview_cache = {}
            instance.log = lambda _message: None
            instance.db_execute(
                "INSERT INTO clips(path,title,description) VALUES(?,?,?)",
                (str(video), "Title", "Description")
            )
            instance.db_execute(
                "INSERT INTO facebook_page_jobs(path,page_id,page_name,publish_at) VALUES(?,?,?,?)",
                (str(video), "page-a", "Page A", self.now.isoformat())
            )

            moved = Path(instance.move_clip_files(str(video), "schedule"))
            self.assertTrue(moved.is_file())
            self.assertEqual(moved.read_bytes(), b"test mp4")
            self.assertEqual(moved.with_suffix(".txt").read_text(encoding="utf-8"), "Title\nDescription")
            self.assertFalse(video.exists())
            self.assertFalse(txt.exists())
            self.assertEqual(instance.get_clips()[0]["path"], str(moved))
            self.assertEqual(instance.get_fb_job(str(moved), "page-a")["path"], str(moved))
            self.assertEqual(instance.selected_path, str(moved))
            instance.conn.close()

    def test_move_clip_files_restores_both_files_when_database_update_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "clip.mp4"
            txt = root / "clip.txt"
            video.write_bytes(b"test mp4")
            txt.write_text("Title\nDescription", encoding="utf-8")

            instance = app.SchedulerApp.__new__(app.SchedulerApp)
            instance.db_lock = threading.Lock()
            instance.conn = sqlite3.connect(":memory:")
            instance.conn.row_factory = sqlite3.Row
            instance.create_db()
            instance.folder_var = SimpleNamespace(get=lambda: str(root))
            instance.selected_path = None
            instance.txt_preview_cache = {}
            instance.log = lambda _message: None

            with self.assertRaisesRegex(RuntimeError, "queue record could not be updated"):
                instance.move_clip_files(str(video), "schedule")

            self.assertTrue(video.is_file())
            self.assertTrue(txt.is_file())
            self.assertFalse((root / "schedule" / "clip.mp4").exists())
            self.assertFalse((root / "schedule" / "clip.txt").exists())
            instance.conn.close()



    def test_scan_worker_imports_mp4_and_matching_txt_into_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "clip.mp4"
            video.write_bytes(b"test-video")
            video.with_suffix(".txt").write_text(
                "A clear title\nFull description with context.\n#shorts",
                encoding="utf-8"
            )
            instance = app.SchedulerApp.__new__(app.SchedulerApp)
            instance.db_lock = threading.Lock()
            instance.conn = sqlite3.connect(":memory:")
            instance.conn.row_factory = sqlite3.Row
            instance.create_db()
            instance.folder_var = SimpleNamespace(get=lambda: str(root))
            instance.youtube_var = SimpleNamespace(get=lambda: True)
            instance.root = SimpleNamespace(after=lambda *_args: None)
            instance.save_settings = lambda: None
            instance.refresh_table = lambda: None
            messages = []
            instance.log = messages.append
            with patch.object(app, "probe_video", return_value=(1080, 1920, 32.0, True)):
                instance._scan_worker(root)
            row = instance.get_clips()[0]
            self.assertEqual(row["title"], "A clear title")
            self.assertIn("Full description with context.", row["description"])
            self.assertEqual((row["width"], row["height"], row["duration"], row["fb_ok"]),
                             (1080, 1920, 32.0, 1))
            self.assertTrue(any("1 matched TXT pairs, 0 missing TXT files" in m for m in messages))
            instance.conn.close()

    def test_facebook_publication_worker_handles_sqlite_rows_and_confirms_published(self):
        now = self.now
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "clip.mp4")
            instance = app.SchedulerApp.__new__(app.SchedulerApp)
            instance.db_lock = threading.Lock()
            instance.conn = sqlite3.connect(":memory:")
            instance.conn.row_factory = sqlite3.Row
            instance.create_db()
            instance.db_execute(
                "INSERT INTO clips(path,title,description) VALUES(?,?,?)",
                (path, "Title", "Description")
            )
            instance.db_execute(
                "INSERT INTO facebook_page_jobs(path,page_id,page_name,publish_at,status,video_id) "
                "VALUES(?,?,?,?,?,?)",
                (path, "page-a", "Page A", (now - timedelta(minutes=10)).isoformat(),
                 "Scheduled", "reel-123")
            )
            instance.secrets = {"fb_pages": [{"id": "page-a", "access_token": "test-token"}]}
            instance.root = SimpleNamespace(after=lambda *_args: None)
            instance.verification_button = SimpleNamespace(configure=lambda **_kwargs: None)
            messages = []
            instance.log = messages.append
            instance.get_clips = lambda: [dict(row) for row in instance.conn.execute(
                "SELECT * FROM clips"
            ).fetchall()]
            instance.organize_clip_after_upload = lambda *_args, **_kwargs: False
            instance.move_completed_queue_to_safe_folder = lambda: 0

            def update_aggregate(clip_path, _pages):
                instance.db_execute(
                    "UPDATE clips SET fb_status='Published' WHERE path=?", (clip_path,)
                )
            instance.update_fb_aggregate = update_aggregate

            response = SimpleNamespace(
                ok=True,
                status_code=200,
                text="",
                json=lambda: {"status": {"publishing_phase": {
                    "publish_status": "published", "status": "complete"
                }}}
            )
            with patch.object(app, "local_now", return_value=now), \
                 patch.object(app.requests, "get", return_value=response) as get_request:
                instance._publication_status_worker(show_dialog=False)

            job = instance.conn.execute(
                "SELECT status FROM facebook_page_jobs WHERE path=?", (path,)
            ).fetchone()
            clip = instance.conn.execute(
                "SELECT fb_status FROM clips WHERE path=?", (path,)
            ).fetchone()
            self.assertEqual(job["status"], "Published")
            self.assertEqual(clip["fb_status"], "Published")
            self.assertEqual(get_request.call_count, 1)
            self.assertTrue(any("1 newly confirmed published" in m for m in messages))
            instance.conn.close()

    def test_facebook_reel_upload_uses_start_binary_upload_and_scheduled_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.mp4"
            video.write_bytes(b"fake-mp4-payload")
            instance = app.SchedulerApp.__new__(app.SchedulerApp)
            instance.secrets = {}
            instance.page_id_var = SimpleNamespace(get=lambda: "")
            instance.raise_graph_error = app.SchedulerApp.raise_graph_error
            instance.stop_event = threading.Event()
            responses = [
                SimpleNamespace(ok=True, status_code=200, text="", content=b'{}',
                                json=lambda: {"video_id": "reel-456", "upload_url": "https://upload.invalid/session"}),
                SimpleNamespace(ok=True, status_code=200, text="", content=b'{"success":true}',
                                json=lambda: {"success": True}),
                SimpleNamespace(ok=True, status_code=200, text="", content=b'{"success":true}',
                                json=lambda: {"success": True, "video_id": "reel-456"}),
            ]
            publish_at = self.now + timedelta(hours=3)
            with patch.object(app.requests, "post", side_effect=responses) as post:
                video_id = instance.upload_facebook_reel(
                    str(video), "Test title", "Test description", publish_at,
                    True, page_id="page-a", page_token="page-token"
                )
            self.assertEqual(video_id, "reel-456")
            self.assertEqual(post.call_count, 3)
            start_data = post.call_args_list[0].kwargs["data"]
            upload_headers = post.call_args_list[1].kwargs["headers"]
            finish_data = post.call_args_list[2].kwargs["data"]
            self.assertEqual(start_data["upload_phase"], "START")
            self.assertEqual(upload_headers["Authorization"], "OAuth page-token")
            self.assertEqual(finish_data["upload_phase"], "FINISH")
            self.assertEqual(finish_data["video_state"], "SCHEDULED")
            self.assertEqual(finish_data["scheduled_publish_time"], str(int(publish_at.timestamp())))
            self.assertEqual(finish_data["is_ai_generated"], "true")

    def test_single_and_multi_selection_filter_the_schedule_scope(self):
        rows = [
            {"path": "one.mp4", "title": "One"},
            {"path": "two.mp4", "title": "Two"},
            {"path": "three.mp4", "title": "Three"},
        ]
        self.assertEqual(
            [row["path"] for row in app.SchedulerApp.filter_queue_rows(rows, ["two.mp4"])],
            ["two.mp4"]
        )
        self.assertEqual(
            [row["path"] for row in app.SchedulerApp.filter_queue_rows(rows, ["one.mp4", "three.mp4"])],
            ["one.mp4", "three.mp4"]
        )
        # No highlighted rows retains the original whole-queue operation.
        self.assertEqual(app.SchedulerApp.filter_queue_rows(rows, []), rows)

    def test_selected_tree_rows_resolve_to_full_video_paths(self):
        instance = app.SchedulerApp.__new__(app.SchedulerApp)
        instance.tree = SimpleNamespace(selection=lambda: ("row-1",))
        instance.tree_path_by_id = {
            "row-1": r"C:\\clips\\first.mp4",
            "row-2": r"D:\\clips\\first.mp4",
        }
        self.assertEqual(instance.get_selected_clip_paths(), [r"C:\\clips\\first.mp4"])
        instance.tree = SimpleNamespace(selection=lambda: ("row-1", "row-2"))
        self.assertEqual(
            set(instance.get_selected_clip_paths()),
            {r"C:\\clips\\first.mp4", r"D:\\clips\\first.mp4"}
        )

    def test_delete_from_list_removes_queue_records_but_keeps_video_and_txt_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "keep-this.mp4"
            txt = root / "keep-this.txt"
            video.write_bytes(b"video stays")
            txt.write_text("Title\\nDescription", encoding="utf-8")

            instance = app.SchedulerApp.__new__(app.SchedulerApp)
            instance.db_lock = threading.Lock()
            instance.conn = sqlite3.connect(":memory:")
            instance.conn.row_factory = sqlite3.Row
            instance.create_db()
            instance.db_execute(
                "INSERT INTO clips(path,title,description) VALUES(?,?,?)",
                (str(video), "Title", "Description")
            )
            instance.db_execute(
                "INSERT INTO facebook_page_jobs(path,page_id,page_name,publish_at,status) VALUES(?,?,?,?,?)",
                (str(video), "page-a", "Page A", self.now.isoformat(), "Pending")
            )
            instance.tree = SimpleNamespace(selection=lambda: ("row-0",))
            instance.tree_path_by_id = {"row-0": str(video)}
            instance.worker = None
            instance.scan_worker = None
            instance.verification_worker = None
            instance.selected_path = str(video)
            instance.selection_title_var = SimpleNamespace(set=lambda _value: None)
            instance.selection_desc = SimpleNamespace(delete=lambda *_args: None)
            instance.txt_preview_cache = {}
            instance.log = lambda _message: None
            instance.refresh_table = lambda: None

            with patch.object(app.messagebox, "askyesno", return_value=True):
                instance.delete_selected_from_list()

            self.assertEqual(instance.get_clips(), [])
            self.assertIsNone(instance.get_fb_job(str(video), "page-a"))
            self.assertTrue(video.is_file())
            self.assertTrue(txt.is_file())
            self.assertIsNone(instance.selected_path)
            instance.conn.close()

    def test_selected_video_title_and_description_are_saved_to_its_queue_row(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "editable.mp4")
            instance = app.SchedulerApp.__new__(app.SchedulerApp)
            instance.db_lock = threading.Lock()
            instance.conn = sqlite3.connect(":memory:")
            instance.conn.row_factory = sqlite3.Row
            instance.create_db()
            instance.db_execute(
                "INSERT INTO clips(path,title,description) VALUES(?,?,?)",
                (path, "Old title", "Old description")
            )
            instance.selected_path = path
            instance.selection_title_var = SimpleNamespace(get=lambda: "A new editable title")
            instance.selection_desc = SimpleNamespace(
                get=lambda *_args: "The matching description is edited independently."
            )
            instance.log = lambda _message: None
            instance.refresh_table = lambda: None

            instance.save_selected_metadata()
            row = instance.get_clips()[0]
            self.assertEqual(row["title"], "A new editable title")
            self.assertEqual(row["description"], "The matching description is edited independently.")
            instance.conn.close()


    def test_windows_installer_is_single_exe_and_dependency_setup_is_install_only(self):
        project = Path(app.__file__).resolve().parent
        readme = (project / "README.md").read_text(encoding="utf-8")
        installer_script = (project / "Install-ScarClipScheduler.ps1").read_text(encoding="utf-8")
        installer_definition = (project / "installer" / "ScarClipScheduler.iss").read_text(encoding="utf-8")
        build_script = (project / "build_windows_exe.ps1").read_text(encoding="utf-8")
        build_workflow = (project / ".github" / "workflows" / "build-exe.yml").read_text(encoding="utf-8")
        release_workflow = (project / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        site = (project / "docs" / "index.html").read_text(encoding="utf-8")
        native_ui = (project / "native" / "ScarClipScheduler.Wpf" / "MainWindow.xaml").read_text(encoding="utf-8")

        self.assertIn("ScarClipScheduler-Setup.exe", readme)
        self.assertIn("## Navigation", readme)
        self.assertIn("[Scheduling workflow](#scheduling-workflow)", readme)
        self.assertEqual(readme.count('src="assets/scarclipscheduler-banner.svg"'), 1)
        self.assertNotIn("scarclipscheduler-mini-banner.svg", readme)
        self.assertNotIn("ScarClipScheduler-Windows-x64.zip", readme)

        self.assertIn("OutputBaseFilename=ScarClipScheduler-Setup", installer_definition)
        self.assertIn("Uninstallable=yes", installer_definition)
        self.assertIn(r'{group}\Uninstall ScarClipScheduler', installer_definition)
        self.assertIn('Filename: "{uninstallexe}"', installer_definition)
        self.assertIn("## Uninstall", readme)
        self.assertIn("Uninstall ScarClipScheduler", readme)
        self.assertIn("InitializeSetup", installer_definition)
        self.assertIn("procedure CurStepChanged(CurStep: TSetupStep)", installer_definition)
        self.assertIn("RaiseException", installer_definition)
        self.assertIn("FinishedLabel=Setup completed successfully.", installer_definition)
        self.assertIn("Start-Transcript", installer_script)
        self.assertIn("installer-setup.log", installer_script)
        self.assertIn("SCARCLIPSCHEDULER SETUP FAILED", installer_script)
        self.assertIn("WindowsPowerShell", installer_definition)
        self.assertIn("function Invoke-CapturedProcess", installer_script)
        self.assertIn("function Invoke-SetupCommand", installer_script)
        self.assertIn("Invoke-CapturedProcess -FilePath $FilePath -Arguments $Arguments", installer_script)
        self.assertIn("if ($result.ExitCode -ne 0)", installer_script)
        self.assertLess(installer_script.index("function Invoke-SetupCommand"), installer_script.index("Invoke-SetupCommand -FilePath $python.File"))
        self.assertIn("Get-Command 'python'", installer_script)
        self.assertIn("Arguments @('--version')", installer_script)
        self.assertIn("sys.version_info >= (3,10)", installer_script)
        self.assertIn("Python.Python.3.14", installer_script)
        self.assertIn("https://www.python.org/downloads/windows/", installer_script)
        self.assertIn("Get-AuthenticodeSignature", installer_script)
        self.assertIn("Python Software Foundation", installer_script)
        self.assertIn("Include_launcher=0", installer_script)
        self.assertNotIn("Python311\\python.exe", installer_script)
        self.assertNotIn("Python312\\python.exe", installer_script)
        self.assertIn(".dependencies-version", installer_script)
        self.assertIn("'pip', 'check'", installer_script)
        self.assertIn("Skipping package installation", installer_script)
        self.assertIn("during installation", installer_script.lower())
        self.assertIn("ScarClipScheduler-Setup.exe", build_script)
        self.assertNotIn("ScarClipScheduler-Windows-x64.zip", build_script)
        self.assertIn("ScarClipScheduler-Setup.exe", build_workflow)
        self.assertIn("ScarClipScheduler-Setup.exe", release_workflow)
        self.assertIn("Remove assets from older releases", release_workflow)
        self.assertIn("github.rest.repos.listReleases", release_workflow)
        self.assertIn("github.rest.repos.listReleaseAssets", release_workflow)
        self.assertIn("github.rest.repos.deleteReleaseAsset", release_workflow)
        self.assertIn("release.id === latestRelease.id", release_workflow)
        self.assertIn(".sort((a, b) => Date.parse(b.published_at) - Date.parse(a.published_at))", release_workflow)
        self.assertNotIn("ScarClipScheduler-Windows-x64.zip", release_workflow)
        self.assertIn("ScarClipScheduler-Setup.exe", site)
        self.assertNotIn("ScarClipScheduler-Windows-x64.zip", site)
        self.assertIn('<ControlTemplate TargetType="{x:Type ComboBox}">', native_ui)
        self.assertIn('Background="{Binding Background, RelativeSource={RelativeSource AncestorType={x:Type ComboBox}}}"', native_ui)
        self.assertIn('Content="{Binding SelectionBoxItem, RelativeSource={RelativeSource AncestorType={x:Type ComboBox}}}"', native_ui)
        self.assertIn('TextElement.Foreground="{Binding Foreground, RelativeSource={RelativeSource AncestorType={x:Type ComboBox}}}"', native_ui)
        self.assertIn('Foreground="{Binding Foreground, RelativeSource={RelativeSource TemplatedParent}}"', native_ui)
        self.assertIn('x:Name="PART_Popup"', native_ui)
        self.assertIn('<Path Data="M 0,0 L 4,4 L 8,0 Z"', native_ui)





class FutureScheduleValidationTests(unittest.TestCase):
    def test_rejects_a_start_time_earlier_than_now(self):
        now = datetime(2026, 11, 22, 16, 15, 0)
        with self.assertRaisesRegex(ValueError, "later than the current local time"):
            backend_service.validate_future_start_at("2026-11-22 16:14", now=now)

    def test_rejects_a_start_time_equal_to_now(self):
        now = datetime(2026, 11, 22, 16, 15, 0)
        with self.assertRaisesRegex(ValueError, "later than the current local time"):
            backend_service.validate_future_start_at("2026-11-22 16:15", now=now)

    def test_accepts_a_future_start_time(self):
        now = datetime(2026, 11, 22, 16, 15, 0)
        result = backend_service.validate_future_start_at("2026-11-22 16:16", now=now)
        self.assertEqual(result, datetime(2026, 11, 22, 16, 16))

    def test_rejects_an_invalid_start_time(self):
        with self.assertRaisesRegex(ValueError, "Choose a valid first post date"):
            backend_service.validate_future_start_at("not-a-date", now=datetime(2026, 11, 22, 16, 15))

    def test_queue_start_rejects_a_past_date_before_touching_settings(self):
        fake_backend = SimpleNamespace(youtube_auth_worker=None, facebook_auth_worker=None)
        past_start = (datetime.now() - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
        with self.assertRaisesRegex(ValueError, "later than the current local time"):
            backend_service.NativeBackend.start_queue(
                fake_backend,
                {
                    "confirmed": True,
                    "start_at": past_start,
                },
            )


class SchedulingConfirmationApiTests(unittest.TestCase):
    """Exercise the real local HTTP handler without starting any uploads."""

    def setUp(self):
        self.backend = Mock()
        self.backend.start_queue.side_effect = self._start_queue
        self.backend_patch = patch.object(backend_service, "BACKEND", self.backend)
        self.backend_patch.start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), backend_service.ApiHandler)
        self.server.api_token = "scheduler-api-contract-test-token"
        self.server.daemon_threads = True
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)
        self.backend_patch.stop()

    def _start_queue(self, data):
        if data.get("confirmed") is not True:
            raise RuntimeError("Scheduling was not sent with an explicit desktop user confirmation.")
        return {"started": True}

    def _post(self, payload, confirmation_header=None):
        request = Request(
            f"http://127.0.0.1:{self.server.server_address[1]}/api/schedule",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Scar-Token": "scheduler-api-contract-test-token",
            },
            method="POST",
        )
        if confirmation_header is not None:
            request.add_header("X-Scar-User-Confirmed", confirmation_header)
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            status = error.code
            body = error.read().decode("utf-8")
            error.close()
            return status, json.loads(body)

    def test_native_confirmation_header_is_promoted_to_boolean_true(self):
        status, payload = self._post({"confirmed": False}, "true")
        self.assertEqual(status, 200)
        self.assertIs(payload["started"], True)
        sent_data = self.backend.start_queue.call_args.args[0]
        self.assertIs(sent_data["confirmed"], True)

    def test_missing_confirmation_is_rejected(self):
        status, payload = self._post({})
        self.assertEqual(status, 400)
        self.assertIn("explicit desktop user confirmation", payload["error"])
        self.backend.start_queue.assert_called_once()
        self.assertNotIn("confirmed", self.backend.start_queue.call_args.args[0])

    def test_legacy_json_confirmation_remains_supported(self):
        status, payload = self._post({"confirmed": True})
        self.assertEqual(status, 200)
        self.assertIs(payload["started"], True)
        sent_data = self.backend.start_queue.call_args.args[0]
        self.assertIs(sent_data["confirmed"], True)

if __name__ == "__main__":
    unittest.main()
