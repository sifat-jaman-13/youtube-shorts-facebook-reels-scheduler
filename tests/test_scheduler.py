import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from unittest.mock import patch

import app


class SchedulerRegressionTests(unittest.TestCase):
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

if __name__ == "__main__":
    unittest.main()
